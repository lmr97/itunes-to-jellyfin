"""
Contains the Track and Playlist classes, as well as 
a set of standalone functions useful in parsing the 
Library.xml file produced by iTunes when you export
your library.
"""
import os
from lxml import etree
from itxml2pl.lib.sanitizers import sanitize_path

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


########################
# STANDALONE FUNCTIONS #
########################

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

        p = Playlist(pl)

        if not p.is_folder():
            continue

        pl_dict.update({p.id: (p.name, p.parent_id)})

    return pl_dict



def lookup_song(track_id_el: etree.Element, 
                tracks_el: etree.Element) -> etree.Element:
    """
    Uses a track ID element from a playlist to get the song info
    out of the all-tracks element.
    """
    track_id = track_id_el.find("integer").text
    track    = tracks_el.xpath(f"key[text()='{track_id}']/following-sibling::dict[1]")[0]

    return track



def fuzzy_search(track_path: str, music_dir: str, dir_sep: str, contains=False) -> str:
    """
    Descend along the track path, returning the correct path if found. 

    track_path: the path to the track file that has not yet been found
    music_dir:  the path to the Music root directory
    dir_sep:    the OS-appropriate directory separator
    contiains:  allow matches to simply contain the current entry string 
                (e.g. "greatest" will match "Greatest Hits"). still accounts 
                for differences in capitalization.

    As an example, if track_path == "/Music/Jane Shepard/Greatest hits/Renegade.ogg"
    and `/Music` is laid out like so -- 

        ```
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
        ```

    this function will first lowercase the artist part of the track_path:

        ```
        /Music/Jane Shepard/Greatest hits/Renegade.ogg
               ------------
               └──> "jane shepard"
        ```

    and seach the directories in /Music, also made lowercase: 

        ```
        ["bobson & the dugnuts", "jane shepard"]
        ```
    
    which it will find the correct directory. But wait! we didn't fix anything.
    If the (previous case) music directory artist name is the same as the one in 
    the track path, then keep searching, since that clearly wasn't the problem.
    
    After this, we would search `/Music/Jane Shepard` ("Greatest Hits") also made 
    lowercase ("greatest hits") against the next part of the track path, likewise
    made lowercase. Since the music directory has a different album directory name
    than the one in the track path, this function will return the fixed path:

        ```
        return "/Music/Jane Shepard/Greatest Hits/Renegade.ogg:
        ```
    
    If the path cannot be located with any case switchup, then it will return 
    a null string.
    """
    rel_tp   = track_path.replace(music_dir, "")    # remove music dir path

    # For he sake of clarity, I am referring to each directory along a path,
    # as well as the name of the file to which it points, as "entries".
    # So `tp_parts` here is a `list` of entries.
    tp_parts = rel_tp.split(dir_sep)

    fixed_path = music_dir

    for tp_entry in tp_parts:

        # no need to check through all entries in directory if the next track_path
        # part already exists
        if os.path.exists(fixed_path+tp_entry):
            fixed_path += tp_entry + dir_sep
            continue

        lc_tp_entry     = tp_entry.lower()
        best_dir_to_add = tp_entry         # either the correct dir or simply from the original path
        curr_dir        = os.listdir(fixed_path)

        for dir_entry in curr_dir:
            lc_de = dir_entry.lower()

            if lc_de == lc_tp_entry:
                best_dir_to_add = dir_entry     # will result in some redundant assignments

            if lc_tp_entry in lc_de and contains:
                best_dir_to_add = dir_entry

        fixed_path += best_dir_to_add + dir_sep

        # if the best directory to append to the fixed path last loop still isn't one that
        # exists, we're not finding the file; return ""
        if not os.path.exists(fixed_path):
            return ""

    # loop adds trailing dir_sep, remove
    fixed_path = fixed_path[:-1]

    return fixed_path



########################
#        CLASSES       #
########################

class _LibraryEntry:
    """
    Base class for both Track and Playlist.
    """
    def __init__(self, el: etree.Element):
        self.el   = el
        self.name = self.get_str_attr("Name", False)

    def get_str_attr(self, attr: str, path_sanitize=True):
        """
        Get any attribute of the song or playlist held in a <string> element. 
        
        It works by getting the next <string> element after the <key> 
        that has `attr` for its text content. This returns a `list` 
        of 1 element. The text attribute of this <string> element 
        object is the attr info.

        Directory seperator is added to be able to sanitize the return value, 
        in case it gets used in a filepath.

        `attr`: The attribute to get within a <string> tag of element
        `path_sanitize`: Whether to replace problematic characters in 
            an attribute value with `_`. Defaults to `True`.

        """

        # get first <string> element after a <key> with
        # text content of `attr`
        string_el_list = self.el.xpath(f"key[text()='{attr}']/following-sibling::string[1]")

        # if the attr is missing, and happens to be Artist or Album,
        # it cannot be null. Otherwise it can be.
        if not string_el_list:
            if attr == "Album":
                return "Unknown Album"

            return ""

        # trim off spaces from end and beginning
        result = string_el_list[0].text
        result = result.lstrip().rstrip()

        if path_sanitize:
            return sanitize_path(result, attr)

        return result




class Track(_LibraryEntry):
    """
    Wrapper class for functions to parse Track `etree.Element`s
    out of the `Library.xml` file.
    """
    def __init__(self, song_el: etree.Element):

        super().__init__(song_el)
        self.name       = sanitize_path(self.name, "Name")
        self.artist     = self.get_str_attr("Artist")
        self.album      = self.get_str_attr("Album")
        self.track_num  = self._get_track_num()
        self.artist_dir = self._get_artist_dir()
        self.file_ext   = self._get_file_ext()



    def _get_track_num(self) -> str:
        """
        Gets track number if it exists and zero-pads it to a 
        width of 2, and adds a space if a track number exists.

        If the track comes from an album with multiple discs,
        then th track's disc number is prepended to the track
        number, with a hyphen in between.
        """

        track_number = ""

        # check for multi-disc album
        disc_count = self.el.xpath("key[text()='Disc Count']/following-sibling::integer[1]")

        if disc_count:
            if int(disc_count[0].text) > 1:
                disc_num = self.el.xpath("key[text()='Disc Number']/following-sibling::integer[1]")

                # sometimes tracks have a disc count, but no listed disc number
                if len(disc_num) > 0:
                    track_number = disc_num[0].text + "-"

        # list returned
        tr_num = self.el.xpath("key[text()='Track Number']/following-sibling::integer[1]")

        if len(tr_num) > 0:

            # we're only padding to a width of 2, so it's simple to implement here
            if len(tr_num[0].text) == 1:
                track_number += "0" + tr_num[0].text + " "
            else:
                track_number += tr_num[0].text + " "       # space added for formatting

        return track_number


    def _get_file_ext(self) -> str:
        """
        Get file extension given file type.
        """
        file_type = self.get_str_attr("Kind")
        file_ext  = None

        if file_type in FILE_EXT_MAP.keys():
            file_ext = FILE_EXT_MAP[file_type]
        else:
            print("\033[0;33mWarning\033[0m: unable to determine file extention for:")
            print(f"\t'{self.name}' by \
                    {self.artist}")
            print("\033[0;33mWarning\033[0m: song not added to playlist")

        return file_ext



    def _get_artist_dir(self):
        """
        The directory in between the Music directory and the album
        directory denotes the artist, with the following precedence:

        1. Compilations (if track is from compilation)
        2. Album Artist
        3. Track Artist
        4. "Unknown Artist"

        This function returns the proper value for the track element.
        """

        compil_elem  = self.el.xpath("key[text()='Compilation']")

        # when a track is a part of a compilation
        if compil_elem:
            return "Compilations"

        # this is the priority by which the artist directory is determined
        priority_attrs = ["Sort Album Artist", "Album Artist", "Sort Artist"]

        # search for and return the first match in the priority list
        for attr in priority_attrs:

            val = self.get_str_attr(attr)

            if val:
                if val == "Various Artists":   # yes, this is how Mac does it
                    return "VARIOUS ARTISTS"

                return val

        # artist has already been gotten, so save time and leave it off the list,
        # and catch the condition outside the loop
        if self.artist:
            return self.artist

        # if all else fails...
        return "Unknown Artist"



class Playlist(_LibraryEntry):
    """
    A wrapper class used to get info about a Playlist element
    in the `Library.xml` file.

    While it would seem intuitive to have `Playlist` objects
    composed of a set of `Track` objects, the conversion
    adds little over simply processing the `etree.Element` object
    directly, and in fact would add a lot of overhead for this
    application.
    """
    def __init__(self, pl_el: etree.Element):
        super().__init__(pl_el)
        self.id         = self.get_str_attr("Playlist Persistent ID", False)
        self.parent_id  = self.get_str_attr("Parent Persistent ID", False)      # parent ID


    def is_folder(self) -> bool:
        """
        Check whether the playlist is a folder or not.
        """
        results = self.el.xpath("key[text()='Folder']")

        # playlists that are not folders do not have a <key>
        # with "Folder" for its text content.
        return (len(results) > 0)


    def make_parent_folder_path(
        self,
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
        path_so_far  = ""
        parents_path = self._parent_folder(self.parent_id, playlist_folders, path_so_far, dir_sep)

        os.makedirs(playlist_dir+parents_path, exist_ok=True)

        return parents_path


    def _parent_folder(
        self,
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

        return self._parent_folder(parent_info[1], folders_table, path_so_far, dir_sep)
