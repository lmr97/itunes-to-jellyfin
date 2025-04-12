from argparse import ArgumentParser
import shutil
from math import ceil
from datetime import datetime

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

    ap.add_argument('-x', '--xml-file',
                    required=False,
                    default="Library.xml",
                    dest="xml_file",
                    metavar="XML_FILE",
                    help="""Filepath to Library.xml. Assumed to be in working directory \
                        if this argument is omitted."""
                    )

    ap.add_argument('-m', '--music-dir',
                    default="",
                    required=False,
                    dest="music_dir",
                    metavar="SVR_MUSIC_DIR",
                    help="Filepath to the directory where iTunes audio files are \
                        stored on the server, added to make M3U paths absolute. If omitted, \
                        all paths will be relative."
                    )

    ap.add_argument('-p', '--playlist-dir',
                    default="Playlists/",
                    required=False,
                    dest="playlist_dir",
                    metavar="PLAYLIST_DIR",
                    help="The directory where you would like your playlist files stored. \
                        If omitted, a directory named \"Playlists\" will be filled with \
                        these files in the working directory."
                    )

    ap.add_argument('-c', '--check-exists',
                    default="warn",
                    choices=["warn", "error", "none"],
                    required=False,
                    dest="check_exists",
                    help="Check if song file at inferred path exists, and either warn or throw an \
                      error. `none` only count if the file was not found, but add it to the playlist \
                      file anyway. Default: warn. Set to `none` if -m is absent. (cannot check path \
                      reliably)."
                    )

    ap.add_argument('-f', '--format',
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

    ap.add_argument('-w', '--dos-filepaths',
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


def show_ext_map(fe_map: dict):
    """
    Prints the FILE_EXT_MAP `dict` in a human-friendly way.
    FILE_EXT_MAP can be found in `parse_fns.py`
    """
    print("\nMapping of file types to extensions used:\n")
    for key, value in fe_map.items():
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

def print_progress_bar(rows_now: int, total_rows: int, func_start_time: datetime):
    """
    Print progress bar, adjusting for console width.
    """
    rows_now = min(rows_now, total_rows)   # cap rows_now

    output_width  = shutil.get_terminal_size(fallback=(80,25))[0]-37   # adjust as terminal changes
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