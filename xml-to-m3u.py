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

NOTE: This program does not support playlist folders, because the relationships
between playlists and their enclosing folder is not clear in iTunes' XML output. 
Playlist folders in the XML appear as simply the union of the tracks in their  
constituent playlists, so it would be prohibitively slow to compute which
playlists belong to a given folder so defined. Playlist folders have to be remade 
manually in Jellyfin, if supported.
"""

import sys
import os
from shutil import get_terminal_size
from math import ceil
from datetime import datetime
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
        if attr == "Artist":
            return "Unknown Artist"
        elif attr == "Album":
            return "Unknown Album"
        else:
            return ""

    return sanitize(string_el_list[0].text)



def sanitize(entry: str) -> str:
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

    # Mac also doesn't like terminal periods (.);
    # ones in the middle of the entry are fine
    if entry[-1] == ".":
        entry = entry[:-1] + "_"

    return entry


def get_track_num(tr: etree.Element) -> str:
    """
    Gets track number if it exists and zero-pads it to a 
    width of 2, and adds a space if a track number exists.
    """
    # list returned
    tr_num = tr.xpath("key[text()='Track Number']/following-sibling::integer[1]")

    if len(tr_num) > 0:

        # we're only padding to a width of 2, so it's simple to implement here
        if len(tr_num[0].text) == 1:
            return ("0" + tr_num[0].text + " ")
        else:
            return (tr_num[0].text + " ")        # space added for formatting
    else:
        return ""


def lookup_song(track_id_el: etree.Element, 
                tracks_el: etree.Element) -> etree.Element:
    """
    Uses a track ID element from a playlist to get the song info
    out of the all-tracks element.
    """
    track_id = track_id_el.xpath("integer")[0].text
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


def parse_xml(cli_opts: dict):
    """
    Interprets CLI options, and then parses XML into
    tracks object and playlists object, calling
    gen_m3u_file() to assemble and write the files.
    """
    # determine filepath separator
    dir_sep = "/"
    if cli_opts['use_dos_filepaths']:
        dir_sep = "\\"

    if cli_opts['flat_music_dir']:
        pass

    print("Loading library XML file...\n")

    library_dom = etree.parse(cli_opts['xml_file'])
    all_tracks  = library_dom.find("dict/dict")             # keep tracks as a single <dict> element
    playlists   = library_dom.findall("dict/array/dict")    # Playlists == <dict>s, list for iter

    # vars for loading bar
    total_playlists = len(playlists)
    proc_start      = datetime.now()

    # "Playlists" that are all/most of the library, and are not user-generated.
    pl_ignores      = ["Library", "Downloaded", "Music"]

    # Create playlist directory if it doesn't exist
    os.makedirs(cli_opts['playlist_dir'], exist_ok=True)

    #########
    # Iterate over playlists
    #########
    print("Starting conversion...\n")
    for i, pl in enumerate(playlists):

        if get_str_attr(pl, "Name") in pl_ignores:
            continue

        # skip playlist folders. see header.
        if is_folder(pl):
            continue

        pl_tracks   = pl.findall("array/dict") # list of track IDs
        track_paths = []
        pl_name     = get_str_attr(pl, 'Name')
        pl_filepath = cli_opts['playlist_dir'] + pl_name + ".m3u"

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
            print(f"\"{pl_name}.m3u\" exists in {cli_opts['playlist_dir']}, skipping...")
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
            title     = get_str_attr(tr, "Name")       # needed regardless
            path      = ""

            if not cli_opts['flat_music_dir']:
                artist = get_str_attr(tr, "Artist")
                album  = get_str_attr(tr, "Album")
                path   = cli_opts['music_dir'] \
                            + dir_sep.join([artist, album, track_num + title]) \
                            + extension + "\n"
            else:
                path = cli_opts['music_dir'] + dir_sep + track_num + title + extension + "\n"

            # validate filepaths, if requested, and music_dir is specified
            if cli_opts['music_dir']:
                if cli_opts['check_exists'] == "warn":

                    if not os.path.exists(path):

                        print("\n\033[0;33mWarning\033[0m: unable to locate file:")
                        print(f"\t'{title}' by {artist}")
                        print(f"Expected it at: {path}")
                        print("\033[0;33mWarning\033[0m: song not added to playlist")

                elif cli_opts['check_exists'] == "error":

                    if not os.path.exists(path):
                        raise FileNotFoundError(f"file {path} not found.")

                # no need to check if cli_opts['check_exists'] == "none",
                # because we wouldn't do anything in that

            # gets here if cli_opts['check_exists'] is "warn" or "none"
            track_paths.append(path)

        with open(pl_filepath, "x", encoding='utf-8') as pl_file:

            pl_file.writelines(track_paths)

        print_progress_bar(i+1, total_playlists, proc_start)



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
        none}         error. Default: warn. Ignored if -m is absent. (cannot check path reliably)
        
    -w                Use MSDOS (Windows) filepath conventions (backslash file separator).

    -f                Flat music directory: all music files are in the same directory, without 
                      any folders between the file and the music directory root. With this option, 
                      all paths are relative only to the music directory root.

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
                    help="Check if song file at inferred path exists, and either warn \
                        the user, throw an error (and terminate), or ignore. Ignored \
                        if -m is absent."
                    )

    ap.add_argument('-w',
                    action="store_true",
                    default=False,
                    required=False,
                    dest="use_dos_filepaths",
                    help="Use MSDOS (Windows) filepath conventions \
                        (backslash file separator)"
                    )

    ap.add_argument('-f',
                    action="store_true",
                    default=False,
                    required=False,
                    dest="flat_music_dir",
                    help="Flat music directory: all music files are in \
                        the same directory, without any folders between \
                        the file and the music directory root. With this \
                        option, all paths are relative only to the music \
                        directory root."
                    )

    ap.add_argument('-t',
                    action="store_true",
                    default=False,
                    dest="show_ext_map",
                    required=False,
                    help="Show mapping of file types to file extensions \
                        used in the program and exit."
                    )

    return vars(ap.parse_args())


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
    following defaults:
    {
        xml_file:          "Library.xml",
        music_dir:         "",
        check_exists:      "warn",
        playlist_dir:      "Playlists/",
        check_exists:      "warn",
        use_dos_filepaths: False,
        flat_music_dir:    False,
        show_ext_map:      False
    }
    """

    cli_opts = parse_cli_args()
    cli_opts = ensure_slash(cli_opts)

    if cli_opts['show_ext_map']:
        show_ext_map()
        return

    try:
        parse_xml(cli_opts)

    except FileNotFoundError as fnfe:

        print(f"\033[0;31mError encountered\033[0m: {repr(fnfe)}")
        print(("\033[0;33mNote\033[0m: this error can be thrown if the file exists, "
            "but was given the wrong extension by this program. To display the way "
            "this program maps file types to extensions, execute the program "
            "with the -t flag.\n"))
        print(("If you would like the program to continue running even when a music "
            "file is not found, execute the program with either `-c warn` or `-c none`.\n"))
        print("\033[0;31mTerminating on error...\033[0m")

        sys.exit(2)     # Linux ENOENT exit status

    print("\n\n\033[0;32mConversion complete!\033[0m\n")


if __name__ == "__main__":
    main()
