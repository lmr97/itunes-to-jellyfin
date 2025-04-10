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
target playlist directory. 
"""

import sys
import os
from shutil import get_terminal_size
from math import ceil
from datetime import datetime, timezone
from argparse import ArgumentParser
from lxml import etree


# these are the extensions iTunes uses when downloading songs
FILE_EXT_MAP = {
    'MPEG audio file':             '.mp3',
    'MPEG-4 video file':           '.m4a',
    'MPEG-4 audio file':           '.mp4',
    'Purchased MPEG-4 video file': '.m4v',
    'AAC audio file':              '.m4a',
    'Purchased AAC audio file':    '.m4a',
    'Matched AAC audio file':      '.m4a',
    'AIFF audio file':             '.aif',
    'WAV audio file':              '.wav'
}


def print_progress_bar(rows_now: int, total_rows: int, func_start_time: datetime):
    """
    Print progress bar, adjusting for console width.
    """
    rows_now = min(rows_now, total_rows)   # cap rows_now

    output_width  = get_terminal_size(fallback=(80,25))[0]-37    # adjust as terminal changes
    completion    = rows_now/total_rows
    bar_width_now = ceil(output_width * completion)

    since_start   = datetime.now() - func_start_time
    est_remaining = since_start * (total_rows/rows_now - 1)
    minutes       = int(est_remaining.total_seconds()) // 60
    seconds       = est_remaining.seconds % 60   # `seconds` attribute can have value > 60

    print("\r| ", "█" * bar_width_now,
            (output_width - bar_width_now) * " ", "|",
            f"{completion:.0%}  ",
            f"Time remaining: {minutes:02d}:{seconds:02d}",
            end = "\r")



###################################################################
# Most of the following are very simple functions, but I thought  #
# wrapping the code in functions makes parse_xml() easier to      #
# read than a ton of comments.                                    #
###################################################################

def get_song_element(tracks_el: etree.Element, track_id: str) -> etree.Element:
    """
    Get song element from the tracks <dict>
    """

    # get first <dict> after <key> with text content of `track_id`
    # within <dict> of tracks
    el_list = tracks_el.xpath(f"key[text()='{track_id}']/following-sibling::dict[1]")

    # extract only element in list
    return el_list[0]


def get_file_ext(song_el: etree.Element) -> str:
    """
    Get file extension given file type.
    """
    file_type = get_str_attr(song_el, "Kind")
    file_ext  = None

    if file_type in FILE_EXT_MAP.keys():
        file_ext = FILE_EXT_MAP[file_type]
    else:
        print("\033[0;33mWarning\033[0m: unable to determine file extention for:")
        print(f"\t'{get_str_attr(song_el,"Name")}' by \
                   {get_str_attr(song_el, "Artist")}")
        print("\033[0;33mWarning\033[0m: song not added to playlist")

    return file_ext


def get_str_attr(el: etree.Element, attr: str):
    """
    Get any attribute of the song or playlist held in a <string> element. 
    
    It works by getting the next <string> element after the <key> 
    that has `attr` for its text content. This returns a `list` 
    of 1 element. The text attribute of this <string> element 
    object is the attr info.

    Directory seperator is added to be able to sanitize the return value, 
    in case it gets used in a filepath.
    """

    # get first <string> element after a <key> with
    # text content of `attr`
    string_el_list = el.xpath(f"key[text()='{attr}']/following-sibling::string[1]")

    # if the attr is missing, and happens to be Artist or Album,
    # it cannot be null. Otherwise it can be.
    if not string_el_list:
        if attr == "Album":
            return "Unknown Album"
        else:
            return ""

    return sanitize(string_el_list[0].text, attr)



def sanitize(entry: str, attribute: str) -> str:
    """
    This function substitutes the occurence of problematic characters
    in a string for an underscore, which is what MacOS does when
    downloading a track. This is so the given string doesn't 
    confuse the OS when it's a part of a path. Most of these characters
    are MacOS' preferences, but a couple are Jellyfin's.
    """
    invalid_chars   = ["/", "\\", "\"", "?", ":", "<", ">", "*", "|"]

    for char in invalid_chars:
        if char in entry:
            entry = entry.replace(char, "_")

    # Mac also doesn't like initial or terminal periods (.);
    # ones in the middle of the entry are fine, anywhere if they are songs.
    if attribute != "Name":

        if entry[-1] == ".":
            entry = entry[:-1] + "_"

        if entry[0] == ".":
            entry = "_" + entry[1:]

    return entry


def get_folder_artist(tr):
    """
    The directory in between the Music directory and the album
    directory denotes the artist, with the following precedence:

    1. Compilations (if track is from compilation)
    2. Album Artist
    3. Track Artist
    4. "Unknown Artist"

    This function returns the proper value for the track element.
    """

    album_artist = get_str_attr(tr, "Album Artist")
    compil_elem  = tr.xpath("key[text()='Compilation']")

    # when a track is a part of a compilation
    if compil_elem:
        return "Compilations"

    if album_artist:
        if album_artist == "Various Artists":   # yes, this is how Mac does it
            return "VARIOUS ARTISTS"

        return album_artist

    track_artist = get_str_attr(tr, "Artist")
    if track_artist:
        return track_artist

    return "Unknown Artist"

def get_track_num(tr: etree.Element) -> str:
    """
    Gets track number if it exists and zero-pads it to a 
    width of 2, and adds a space if a track number exists.

    If the track comes from an album with multiple discs,
    then th track's disc number is prepended to the track
    number, with a hyphen in between.
    """

    track_number = ""

    # check for multi-disc album
    disc_count = tr.xpath("key[text()='Disc Count']/following-sibling::integer[1]")

    if disc_count:
        if int(disc_count[0].text) > 1:
            disc_num = tr.xpath("key[text()='Disc Number']/following-sibling::integer[1]")

            # sometimes tracks have a disc count, but no listed disc number
            if len(disc_num) > 0:
                track_number = disc_num[0].text + "-"

    # list returned
    tr_num = tr.xpath("key[text()='Track Number']/following-sibling::integer[1]")

    if len(tr_num) > 0:

        # we're only padding to a width of 2, so it's simple to implement here
        if len(tr_num[0].text) == 1:
            track_number += "0" + tr_num[0].text + " "
        else:
            track_number += tr_num[0].text + " "       # space added for formatting

    return track_number


def lookup_song(track_id_el: etree.Element, 
                tracks_el: etree.Element) -> etree.Element:
    """
    Uses a track ID element from a playlist to get the song info
    out of the all-tracks element.
    """
    track_id = track_id_el.find("integer").text
    track    = tracks_el.xpath(f"key[text()='{track_id}']/following-sibling::dict[1]")[0]

    return track


def is_folder(playlist: etree.Element) -> bool:
    """
    Check whether the playlist is a folder or not.
    """
    results = playlist.xpath("key[text()='Folder']")

    # playlists that are not folders do not have a <key>
    # with "Folder" for its text content.
    return (len(results) > 0)


def sanitize_xml(text: str) -> str:
    """
    Substitute problematic characters (&, <, >) for 
    escaped versions in text meant element data 
    (not for attributes, since attributes aren't edited
    in this project)
    """

    text = text.replace("&", "&amp;")   # have to start with &, or else escapes get funky
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")

    return text


def write_xml_playlist(playlist_filepath: str, pl_name: str, track_paths: list, dir_sep: str):
    """
    Writes XML files from playlist info. Some headers are missing,
    like owner user ID, genres, and runtime, but these can be 
    populated by a library scan (relatively brief if already
    done on library as a whole).
    """
    # sanitize
    pl_name_sanitized = sanitize_xml(pl_name)
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
        path_el.text = sanitize_xml(track_path[:-1])      # shave off newline added by parse_xml()

        # append it to <PlaylistItems> element,
        # which by extension adds it to `pl_xml`
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


def get_pl_folders(playlists: etree.Element) -> dict:
    """
    Scans the list of playlists, and assembles a `dict` where each 
    key-value pair following form:

        <Persistent ID>: (<playlist name>, <Parent Persisent ID>)
    
    The key is a str, and the value is a 2-tuple. This `dict` is generated
    to save time and computing resources later on. 
    
    It was thought to be more effecient than passing the whole (potentially 
    large) XML element down a chain of recursion, and instead passing a `dict`
    down it. 
    """

    pl_dict = dict()
    for pl in playlists:

        if not is_folder(pl):
            continue

        pl_id   = get_str_attr(pl, "Playlist Persistent ID")
        pl_name = get_str_attr(pl, "Name")
        par_id  = get_str_attr(pl, "Parent Persistent ID")      # parent ID

        pl_dict.update({pl_id: (pl_name, par_id)})

    return pl_dict

def make_parent_folder_path(
    playlist:         etree.Element,
    playlist_folders: dict,
    playlist_dir:     str,
    dir_sep:          str) -> str:
    """
    Some playlists are kept in playlist folders in iTunes.
    If a playlist is in a folder, the library XML has a <key>
    with "Parent Persistent ID", which is the "Persistent ID"
    of another "playlist" listed, of type Folder.

    This function takes a playlist, as well as a `dict` playlists,
    (made in `get_pl_folders()`), produces a path to insert into 
    the playlist's filepath, mirroring the user's playlist 
    folder structure within iTunes in the playlist directory 
    the user specified. It also create the directories necessary
    in the playlist directory

    It does this through recursion. See parent_folder() for recursive 
    componenent.
    """
    pl_parent_id = get_str_attr(playlist, "Parent Persistent ID")
    path_so_far  = ""
    parents_path = parent_folder(pl_parent_id, playlist_folders, path_so_far, dir_sep)

    os.makedirs(playlist_dir+parents_path, exist_ok=True)

    return parents_path


def parent_folder(
    pl_parent_id:  str,
    folders_table: dict,
    path_so_far:   str,
    dir_sep:       str) -> str:
    """
    Recurses through playlist folder table to get the path from
    playlist directory to the playlist, as it is organized in iTunes.
    """

    # break condition
    if not pl_parent_id:
        return path_so_far

    parent_info  = folders_table[pl_parent_id]
    path_so_far  = parent_info[0] + dir_sep + path_so_far

    return parent_folder(parent_info[1], folders_table, path_so_far, dir_sep)



def parse_xml(cli_opts: dict):
    """
    Interprets CLI options, and then parses XML into
    tracks object and playlists object, building track paths, and 
    writing a file of the appropriate type and location.
    """
    # determine filepath separator
    dir_sep = "/"
    if cli_opts['use_dos_filepaths']:
        dir_sep = "\\"

    # this conditional pops up enough to justify making
    # a single boolean for it
    xml_output = True
    if cli_opts['output_format'] == "m3u":
        xml_output = False

    # similarly, this appears often enough to be worth
    # saving in its own variable
    pl_dir = cli_opts['playlist_dir']

    print("Loading library XML file...\n")

    library_dom = etree.parse(cli_opts['xml_file'])
    all_tracks  = library_dom.find("dict/dict")             # keep tracks as a single <dict> element
    playlists   = library_dom.findall("dict/array/dict")    # Playlists == <dict>s, list for iter
    pl_folders  = get_pl_folders(playlists)                 # the playlists folders made in iTunes

    # vars for loading bar
    total_playlists  = len(playlists)        # includes folders, will update as folders are found
    proc_start       = datetime.now()

    # "Playlists" that are all/most of the library, and are not user-generated.
    pl_ignores       = ["Library", "Downloaded", "Music", "Recently Added"]
    total_playlists -= 4                     # take off 3 for the list above

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
    for i, pl in enumerate(playlists):

        if get_str_attr(pl, "Name") in pl_ignores:
            continue

        # skip playlist folders. see header.
        if is_folder(pl):
            total_playlists -= 1    # number originally included folders, adjust that here
            continue

        pl_incomplete = False
        pl_tracks     = pl.findall("array/dict") # list of track IDs
        pl_name       = get_str_attr(pl, 'Name')
        pl_filepath   = pl_dir + make_parent_folder_path(pl, pl_folders, pl_dir, dir_sep)
        track_paths   = []

        pl_tracks_not_found = set()

        # determine filepath
        if xml_output:
            pl_filepath  = dir_sep.join([pl_filepath, pl_name, "playlist.xml"])
        else:
            pl_filepath += dir_sep + pl_name + ".m3u"

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
                print((f"\"{pl_name}/playlist.xml\" exists in "
                    f"{pl_dir}, skipping..."))
            else:
                print((f"\"{pl_name}.m3u\" exists in {pl_dir}, skipping..."))

            continue

        #########
        # Iterate over tracks of playlist
        #########
        for tr_id_el in pl_tracks:

            tr = lookup_song(tr_id_el, all_tracks)

            # check ext first, because that will allow a song to be skipped
            extension = get_file_ext(tr)
            if not extension:
                continue

            track_num = get_track_num(tr)
            title     = get_str_attr(tr, "Name")        # needed regardless
            path      = ""

            artist = get_folder_artist(tr)              # album artist is needed
            album  = get_str_attr(tr, "Album")
            path   = cli_opts['music_dir'] \
                        + dir_sep.join([artist, album, track_num + title]) \
                        + extension

            all_tracks_in_pls.add(path)             # count unique tracks encountered

            if not os.path.exists(path):

                # always track, even when option is "none" (see print statments at end of function)
                pl_tracks_not_found.add(path+"\n")      # add path to set
                all_tracks_not_found.add(path+"\n")
                pl_incomplete = True

                # validate filepaths, if requested
                if cli_opts['check_exists'] == "warn":

                    print("\n\033[0;33mWarning\033[0m: unable to locate file:")
                    print(f"\t'{title}' by {get_str_attr(tr, "Artist")}")
                    print(f"Expected it at: \"{path}\"")
                    print("\033[0;33mWarning\033[0m: song not added to playlist")
                    continue

                if cli_opts['check_exists'] == "error":

                    # don't need to worry about track misses and playlist completion,
                    # since an error is raised when the first of either occurs
                    raise FileNotFoundError(f"file {path} not found.")

            # execution reaches here if either:
            # 1) file exists
            # 2) check_exists != warn AND check_exists != error
            track_paths.append(path+"\n")

        if pl_incomplete:
            incomplete_playlists.append(pl_name+"\n")

        # write out to file, with the correct format
        if xml_output:
            write_xml_playlist(pl_filepath, pl_name, track_paths, dir_sep)
        else:
            with open(pl_filepath, "w+", encoding='utf-8') as pl_file:
                pl_file.writelines(track_paths)

        # write out file of missed tracks from the playlist,
        # in file named <playlist name>/playlist.missing for XMLs
        # or <playlist name>.m3u.missing for M3Us.
        missing_tr_file_path = pl_filepath.split(dir_sep)
        if xml_output:
            missing_tr_file_path[-1]  = "playlist.missing"  # change file extension
        else:
            missing_tr_file_path[-1] += ".missing"          # append after file extension

        missing_tr_file_path = dir_sep.join(missing_tr_file_path)

        # NOTE: since a `set` was used to keep track of missing tracks,
        # the order these tracks will be written to this file cannot be
        # known in advance.
        with open(missing_tr_file_path, "w+", encoding='utf-8') as missing_tr_file:
            missing_tr_file.writelines(pl_tracks_not_found)

        print_progress_bar(i+1, total_playlists, proc_start)

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



def parse_cli_args() -> dict:
    """
    Here are the options parsed for, and their descriptions

    -x XMLFILE        Filepath to Library.xml. Assumed to be in working directory if omitted. 

    -m SVR_MUSIC_DIR  Filepath to the directory where iTunes audio files are stored on
                      the server, added to make M3U paths absolute. If omitted, all paths will 
                      be relative.

    -p PLAYLIST_DIR   The directory where you would like your playlist files stored. It will be 
                      created if it does not exist. If omitted, a directory named "Playlists" 
                      will be created in the working directory (if necessary) and filled with 
                      the playlist files. 
                      

    -c {warn, error,  Check if song file at inferred path exists, and either warn or throw an 
        none}         error. `none` only count if the file was not found, but add it to the playlist
                      file anyway. Default: warn. Set to `none` if -m is absent. (cannot check path 
                      reliably). 

    -f {m3u, xml}     The format to output the playlists info into. Defaults to XML. If `xml`
                      is chosen, the file will be formatted like Jellyfin's playlist XMLs,
                      but with <RunningTime>, <Genres>, and <OwnerUserID> tags omitted, as they
                      can be filled in with a rescan of the library (this will be relatively
                      brief if the music has been scanned already).    

    -w                Use MSDOS (Windows) filepath conventions (backslash file separator).

    -t                Show mapping of file types to file extensions used in the program and exit.

    -h                Display this help info and exit. (-h is added in ArgumentParser by default)
    """
    ap = ArgumentParser(
        description="A simple utility to generate .m3u files from an iTunes / Apple Music's \
            exported Library file (XML)"
        )

    ap.add_argument('-x',
                    required=False,
                    default="Library.xml",
                    dest="xml_file",
                    metavar="XML_FILE",
                    help="""Filepath to Library.xml. Assumed to be in working directory \
                        if this argument is omitted."""
                    )

    ap.add_argument('-m',
                    default="",
                    required=False,
                    dest="music_dir",
                    metavar="SVR_MUSIC_DIR",
                    help="Filepath to the directory where iTunes audio files are \
                        stored on the server, added to make M3U paths absolute. If omitted, \
                        all paths will be relative."
                    )

    ap.add_argument('-p',
                    default="Playlists/",
                    required=False,
                    dest="playlist_dir",
                    metavar="PLAYLIST_DIR",
                    help="The directory where you would like your playlist files stored. \
                        If omitted, a directory named \"Playlists\" will be filled with \
                        these files in the working directory."
                    )

    ap.add_argument('-c',
                    default="warn",
                    choices=["warn", "error", "none"],
                    required=False,
                    dest="check_exists",
                    help="Check if song file at inferred path exists, and either warn or throw an \
                      error. `none` only count if the file was not found, but add it to the playlist \
                      file anyway. Default: warn. Set to `none` if -m is absent. (cannot check path \
                      reliably)."
                    )

    ap.add_argument('-f',
                    default="xml",
                    choices=["xml", "m3u"],
                    required=False,
                    dest="output_format",
                    help="The format to output the playlists info into. Defaults to XML. If `xml` \
                      is chosen, the file will be formatted like Jellyfin's playlist XMLs, \
                      but with <RunningTime>, <Genres>, and <OwnerUserID> tags omitted, as they \
                      can be filled in with a rescan of the library (this will be relatively \
                      brief if the music has been scanned already)."
                    )

    ap.add_argument('-w',
                    action="store_true",
                    default=False,
                    required=False,
                    dest="use_dos_filepaths",
                    help="Use MSDOS (Windows) filepath conventions \
                        (backslash file separator)"
                    )

    # ap.add_argument('-l',
    #                 action="store_true",
    #                 default=False,
    #                 required=False,
    #                 dest="flat_music_dir",
    #                 help="Flat music directory: all music files are in \
    #                     the same directory, without any folders between \
    #                     the file and the music directory root. With this \
    #                     option, all paths are relative only to the music \
    #                     directory root."
    #                 )

    ap.add_argument('-t',
                    action="store_true",
                    default=False,
                    dest="show_ext_map",
                    required=False,
                    help="Show mapping of file types to file extensions \
                        used in the program and exit."
                    )

    cli_args = vars(ap.parse_args())

    # ignore file existence check response option if music_dir isn't specified
    if not cli_args['music_dir']:
        cli_args['check_exists'] = "none"

    return cli_args


def show_ext_map():
    """
    Prints the FILE_EXT_MAP `dict` all nice
    """
    print("\nMapping of file types to extensions used:\n")
    for key, value in FILE_EXT_MAP.items():
        print(f'\t{key:<28}->{value:>6}')

    print()


def ensure_slash(opts: dict) -> dict:
    """
    Makes sure the directory paths provided by the user end 
    with the OS-appropriate slash. This makes assembling the 
    paths much easier, since I can simply prepend it to the 
    rest of the path regardless of whether it is null or not.
    """
    fp_slash = "/"
    if opts['use_dos_filepaths']:
        fp_slash = "\\"

    if opts['playlist_dir'][-1] != fp_slash:
        opts['playlist_dir'] += fp_slash

    if opts['music_dir']:
        if opts['music_dir'][-1] != fp_slash:
            opts['music_dir'] += fp_slash

    return opts

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
        output_format:     "xml",
        use_dos_filepaths: False,
        show_ext_map:      False
    }
    """

    cli_opts = parse_cli_args()
    cli_opts = ensure_slash(cli_opts)

    if cli_opts['show_ext_map']:
        show_ext_map()
        return

    parse_xml(cli_opts)
    # try:
    #     parse_xml(cli_opts)

    # except FileNotFoundError as fnfe:

    #     print(f"\033[0;31mError encountered\033[0m: {repr(fnfe)}")
    #     print(("\033[0;33mNote\033[0m: this error can be thrown if the file exists, "
    #         "but was given the wrong extension by this program. To display the way "
    #         "this program maps file types to extensions, execute the program "
    #         "with the -t flag.\n"))
    #     print(("If you would like the program to continue running even when a music "
    #         "file is not found, execute the program with either `-c warn` or `-c none`.\n"))
    #     print("\033[0;31mTerminating on error...\033[0m")

    #     sys.exit(2)     # Linux ENOENT exit status

    # except Exception as e:
    #     print(f"\033[0;31mUnexpected error encountered\033[0m: {repr(e)}")
    #     print("\033[0;31mTerminating on error...\033[0m")
    #     sys.exit(1)

    print("\n\n\033[0;32mConversion complete!\033[0m\n")


if __name__ == "__main__":
    main()
