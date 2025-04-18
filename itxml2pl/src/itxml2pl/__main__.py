"""
A utility to generate .m3u files from an iTunes / Apple Music exported 
library file (Library.xml).

The XML file that iTunes / Apple Music (iT/AM) exports as "Library.xml" has two
major sections after the header: 

    1. A dictionary (<dict>) of all tracks in the library and their info (each 
       as <dict>s), with an ID number assigned to each. This ID functions
       as the <key>, and 
    2. A list (<array>) of playlists, composed of the IDs of the tracks they
       contain.

This utility first gets the list of tracks as the `all_tracks` variable, accessible
via ID <key>s. Then it gets the <array> of playlists, and cross references each ID
against the `all_tracks` DOM object to build the paths to each song for
the M3U file. It makes one .m3u file for each playlist, placing each in the 
"Playlist" folder.

This, of course, assumes the music directory you're keeping your music in is
organized into folders for each artist, with subfolders for each release by
that artist, and all songs are in these release subfolders. An example 
organization would be:

    Music
    ├── Bobson & the Dugnuts
    │   ├── Day on the Diamond
    │   │   ├── Big in Japan.mp3
    │   │   ├── Sakura Bat.mp3
    │   │   └── Tokyo Pitch.mp3
    │   └── World Tour 1993
    │       └── Sakura Bat (Live).mp3
    └── Jane Shepard
        └── Greatest Hits
            ├── Renegade.ogg
            └── All Tuchanka is Green.mp4

If all your music files are in the same folder, without any intermediate folders,
you can use the `-f` flag on this program and it'll work just fine. (note: iT/AM 
does not download music this way by default, but it can).

This program supports playlist organization into folders: it mirrors the
structure of playlist folders in iTunes as given in the library file in the
target playlist directory. These folders won't show up in your list of playlists,
however, since you'll simply have a flat list of all your playlists, despite
the structure of the Playlist directory that this program makes. So, there's no
great way to in Jellyfin to replicate iTunes' playlist folder feature. The
closest thing in Jellyfin is something called "collections", which are used
to organize any media items, not just music or playlists, so collections 
have their own section in your Jellyfin library. You could make a collection of
playlists if you wanted, but it won't clean up your playlists. Regardless, the
correct directory structure is there for you to use as you see fit.
"""

import sys
import os
from datetime import timezone, datetime
from lxml import etree
from itxml2pl.lib import gen_utils, parsers, sanitizers
from itxml2pl.lib.parsers import Track, Playlist    # I want these classes by name


def write_xml_playlist(playlist_filepath: str, pl_name: str, track_paths: list, dir_sep: str):
    """
    Writes XML files from playlist info. Some headers are missing,
    like owner user ID, genres, and runtime, but these can be 
    populated by a library scan (relatively brief if already
    done on library as a whole).
    """
    # sanitize
    pl_name_sanitized = sanitizers.sanitize_xml(pl_name)
    pl_xml = etree.XML(
        (
            "<Item>"
            "<Added>"
            f"{datetime.now(timezone.utc).strftime("%m/%d/%Y %H:%M:%S")}"
            "</Added>"
            "<LockData>false</LockData>"
            f"<LocalTitle>{pl_name_sanitized}</LocalTitle>"
            "<PlaylistItems />"
            "<Shares />"
            "<PlaylistMediaType>Audio</PlaylistMediaType>"
            "</Item>"
        )
    )
    pl_xml_tree = etree.ElementTree(pl_xml)   # for native write() method

    # all playlist items will be appended to this one. Element.find()
    # returns a reference to the element, not a copy (thank god)
    pl_items_el = pl_xml_tree.find("PlaylistItems")

    for track_path in track_paths:

        # build <PlaylistItem> element
        pl_track     = etree.Element("PlaylistItem")
        path_el      = etree.SubElement(pl_track, "Path")
        path_el.text = sanitizers.sanitize_xml(track_path[:-1])    # shave off \n from parse_xml()

        # append it to <PlaylistItems> element,
        # which by tr.file_ext adds it to `pl_xml`
        pl_items_el.append(pl_track)

    # Jellyfin puts all its playlist XMLs in folders with the name of the playlist,
    # so create one if need be
    playlist_parent_dir = playlist_filepath.split(dir_sep)
    playlist_parent_dir = dir_sep.join(playlist_parent_dir[:-1])
    os.makedirs(playlist_parent_dir, exist_ok=True)

    # will create file if it doesn't exist
    pl_xml_tree.write(
        playlist_filepath,
        pretty_print=True,
        xml_declaration=True,
        encoding='utf-8',
        standalone=True
    )



def parse_xml(cli_opts: dict):
    """
    Interprets CLI options, and then parses XML into
    tracks object and playlists object, building track paths, and 
    writing a file of the appropriate type and location.
    """
    # commonly used variables below that warrant their own
    # shorter names
    dir_sep = "/"
    if cli_opts['use_dos_filepaths']:
        dir_sep = "\\"

    xml_output = True
    if cli_opts['output_format'] == "m3u":
        xml_output = False

    pl_dir = cli_opts['playlist_dir']


    print("Loading library XML file...\n")
    try:
        library_dom = etree.parse(cli_opts['xml_file'])
    except OSError as ose:
        print(f"Unable to find Library.xml file at {cli_opts['xml_file']}.")
        print(f"Error text: {repr(ose)}")
        raise OSError from ose

    all_tracks  = library_dom.find("dict/dict")             # keep tracks as a single <dict> element
    playlists   = library_dom.findall("dict/array/dict")    # Playlists == <dict>s, list for iter
    pl_folders  = parsers.get_pl_folders(playlists)         # the playlists folders made in iTunes

    # vars for loading bar
    total_playlists  = len(playlists)        # includes folders, will update as folders are found
    proc_start       = datetime.now()

    # "Playlists" that are all/most of the library, and are not user-generated.
    pl_ignores       = ["Library", "Downloaded", "Music", "Recently Added"]
    total_playlists -= len(pl_ignores)                      # decrement by list length above

    # Create playlist directory if it doesn't exist
    os.makedirs(pl_dir, exist_ok=True)

    # track missing tracks and altered playlists
    all_tracks_in_pls    = set()
    all_tracks_not_found = set()    # count only unique misses
    incomplete_playlists = []

    #########
    # Iterate over playlists
    #########
    print("Starting conversion...\n")
    for i, plist in enumerate(playlists):

        pl = Playlist(plist)

        if pl.name in pl_ignores:
            continue

        # skip playlist folders. see header.
        if pl.is_folder():
            total_playlists -= 1    # number originally included folders, adjust that here
            continue

        pl_incomplete = False
        pl_tracks     = pl.el.findall("array/dict")     # list of track IDs
        pl_filepath   = pl_dir + pl.make_parent_folder_path(pl_folders, pl_dir, dir_sep)
        track_paths   = []

        pl_tracks_not_found = set()

        # determine filepath
        pl_name_sanitized = sanitizers.sanitize_path(pl.name, "Name")
        if xml_output:
            pl_filepath  = dir_sep.join([pl_filepath, pl_name_sanitized, "playlist.xml"])
        else:
            pl_filepath += dir_sep + pl_name_sanitized + ".m3u"

        # defaulting to not overwriting existing files.
        #
        # I am assuming that if an M3U file of the exact name of the
        # playlist exists, in the playlist directory specified by the
        # user, it probably is the way the user wants it. It may even be
        # from an earlier run of this very program, which may have been
        # cut short due to an exception raised or simply early termination.
        #
        # This requires the user to delete the existing playlist files,
        # preventing accidental overwrites.
        if os.path.exists(pl_filepath):
            if xml_output:
                print((f"\"{pl.name}/playlist.xml\" exists in "
                    f"{pl_dir}, skipping..."))
            else:
                print((f"\"{pl.name}.m3u\" exists in {pl_dir}, skipping..."))

            continue

        #########
        # Iterate over tracks of playlist
        #########
        for tr_id_el in pl_tracks:

            tr_el = parsers.lookup_song(tr_id_el, all_tracks)
            tr    = Track(tr_el)

            # path to check for file existence; may not be the same as path included in
            # playlist file if Jellyfin runs in a container.
            rel_path   = dir_sep.join([tr.artist_dir, tr.album, tr.track_num + tr.name]) \
                            + tr.file_ext
            check_path = cli_opts['music_dir'] + rel_path


            if cli_opts['docker_dir']:
                path = cli_opts['docker_dir'] + rel_path
            else:
                path = check_path


            all_tracks_in_pls.add(check_path)             # count unique tracks encountered

            if not os.path.exists(check_path):

                # try and find the track, with a fuzzy search
                corrected_path = parsers.fuzzy_search(check_path,
                    cli_opts['music_dir'],
                    dir_sep,
                    contains=True)

                if not os.path.exists(corrected_path):

                    # always track, even when option is "none" (see prints at end of function)
                    if not corrected_path:
                        pl_tracks_not_found.add(check_path+"\n")          # add original path to set
                        all_tracks_not_found.add(check_path+"\n")
                    else:
                        pl_tracks_not_found.add(corrected_path+"\n")      # add failed correction
                        all_tracks_not_found.add(corrected_path+"\n")

                    pl_incomplete = True

                    # validate filepaths, if requested
                    if cli_opts['check_exists'] == "warn":

                        print("\n\033[0;33mWarning\033[0m: unable to locate file:")
                        print(f"\t'{tr.name}' by {tr.artist}")
                        print(f"Expected it at: \"{path}\"")
                        print("\033[0;33mWarning\033[0m: song not added to playlist")
                        continue

                    if cli_opts['check_exists'] == "error":

                        # don't need to worry about track misses and playlist completion,
                        # since an error is raised when the first of either occurs
                        raise FileNotFoundError(f"file {path} not found.")
                else:
                    path = corrected_path

            # execution reaches here if either:
            # 1) file exists
            # 2) check_exists != warn AND check_exists != error
            track_paths.append(path+"\n")

        if pl_incomplete:
            incomplete_playlists.append(pl.name+"\n")

        # write out to file, with the correct format
        if xml_output:
            write_xml_playlist(pl_filepath, pl.name, track_paths, dir_sep)
        else:
            with open(pl_filepath, "w+", encoding='utf-8') as pl_file:
                pl_file.writelines(track_paths)

        # write out file of missed tracks from the playlist,
        # in file named <playlist name>/playlist.missing for XMLs
        # or <playlist name>.m3u.missing for M3Us.
        missing_tr_file_path = pl_filepath.split(dir_sep)
        if xml_output:
            missing_tr_file_path[-1]  = "playlist.missing"  # change file tr.file_ext
        else:
            missing_tr_file_path[-1] += ".missing"          # append after file tr.file_ext

        missing_tr_file_path = dir_sep.join(missing_tr_file_path)

        # NOTE: since a `set` was used to keep track of missing tracks,
        # the order these tracks will be written to this file cannot be
        # known in advance.
        with open(missing_tr_file_path, "w+", encoding='utf-8') as missing_tr_file:
            missing_tr_file.writelines(pl_tracks_not_found)

        gen_utils.print_progress_bar(i+1, total_playlists, proc_start)

    # make list of playlists that had any missing tracks, named
    # named "00incomplete_playlists.txt" in the given playlist directory
    with open(pl_dir+"00incomplete_playlists.txt", "w+", encoding='utf-8') as incomp_pl_file:
        incomp_pl_file.writelines(incomplete_playlists)

    # make list of all filepaths for songs that weren't found,
    # and put it in the playlist directory root. Uses M3U format
    # regardless of playlist format to help user better locate
    # missing tracks
    with open(pl_dir+"00tracks_not_found.m3u", "w+", encoding='utf-8') as tr_not_found_file:
        tr_not_found_file.writelines(all_tracks_not_found)

    # print this regardless
    # "tracks not found" measures the number of tracks that are in playlists,
    # but were not found in the file system
    print(f"\n\nTracks not found:     {len(all_tracks_not_found)} / {len(all_tracks_in_pls)}")
    print(f"Playlists incomplete: {len(incomplete_playlists)} / {total_playlists}")



def main():
    """
    When taking command-line arguments, a `dict` is generated with the 
    command line arguments. If omitted (which all can be), the following 
    defaults are returned:

    {
        xml_file:          "Library.xml",
        music_dir:         "",
        playlist_dir:      "Playlists/",
        check_exists:      "warn",
        docker_dir:        "",
        output_format:     "xml",
        use_dos_filepaths: False,
        show_ext_map:      False
    }
    """

    cli_opts = gen_utils.parse_cli_args()
    cli_opts = gen_utils.ensure_slash(cli_opts)

    if cli_opts['show_ext_map']:
        gen_utils.show_ext_map(parsers.FILE_EXT_MAP)
        return

    if cli_opts['debug_mode']:

        parse_xml(cli_opts)

    else:
        try:
            parse_xml(cli_opts)

        except FileNotFoundError as fnfe:

            print(f"\033[0;31mError\033[0m: {repr(fnfe)}")
            print(("\033[0;33mNote\033[0m: this error can be thrown if the file exists, "
                "but was given the wrong tr.file_ext by this program. To display the way "
                "this program maps file types to tr.file_exts, execute the program "
                "with the -t flag.\n"))
            print(("If you would like the program to continue running even when a music "
                "file is not found, execute the program with either `-c warn` or `-c none`.\n"))
            print("\033[0;31mTerminating on error...\033[0m")

            sys.exit(2)     # Linux ENOENT exit status
        except PermissionError as pe:

            print(f"\033[0;31mError\033[0m: {repr(pe)}")

            # see what the permissions are
            music_dir_stat = os.stat(cli_opts['music_dir'])
            pl_dir_stat    = os.stat(cli_opts['playlist_dir'])

            print(("Note: Jellyfin's configs (or possibly also your music library)"
                "may belong to either the root user or the user that Jellyfin"
                "uses to interact with the OS, `jellyfin`. Here are the file permissions"
                "for the directories used:\n"))

            print(f"Music directory:      {cli_opts['music_dir']}")
            print(f"    Owner: {music_dir_stat.st_uid}")
            print(f"     Mode: {music_dir_stat.st_mode}")
            print(f"Playlists directory:  {cli_opts['playlist_dir']}")
            print(f"    Owner: {pl_dir_stat.st_uid}")
            print(f"     Mode: {pl_dir_stat.st_mode}")

            print("\n\033[0;31mTerminating on error...\033[0m")

        except OSError:
            sys.exit(2)

        except Exception as e:
            print(f"\033[0;31mUnexpected error encountered\033[0m: {repr(e)}")
            print("\033[0;31mTerminating on error...\033[0m")
            sys.exit(1)

    print("\n\n\033[0;32mConversion complete!\033[0m\n")


# if __name__ == "__main__":
#     main()
