"""
Sanitizing utilities for filepaths and for XML.
"""

def sanitize_path(entry: str, attribute: str) -> str:
    """
    This function substitutes the occurence of problematic characters
    in a string for an underscore, which is what MacOS does when
    downloading a track. This is so the given string doesn't 
    confuse the OS when it's a part of a path. Most of these characters
    are MacOS' preferences, but a couple are Jellyfin's.
    """
    invalid_chars   = ["/", "\\", "\"", "'", "?", ":", "<", ">", "*", "|"]

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