# iTunes / Apple Music Migration to Jellyfin &mdash; with playlists!

## Introduction

This guide is for MacOS users who use the iTunes Store to *download* music, instead of using Apple's streaming service, Apple Music. Although the app formerly known as iTunes was renamed to Music, I will retain the old name here for simplicity.

Long-time iTunes users may be familiar with the (now legacy) service <b>iTunes Match</b>, which allows users to back up non-iTunes songs to Apple's cloud to be a part of the same library. Since this service is on the way out, some songs simply get dropped (especially rare ones). I recently got burned on this, inspiring me to make the migration from iTunes to my own server, using software designed for the purpose of keeping my music, not renting out space to me for the convenience. 

One of the most common music server software options I saw mentioned was [Jellyfin](https://jellyfin.org/); it looks nice, and has plenty of support and documentation, so that's what I chose for the migration target. There was almost no documentation on how to migrate to Jellyfin from iTunes, however, especially if you want to <b>preserve your playlists</b>, so this repo serves to fill that gap, with both a walk-through and custom-made tools to get the job done.

## My setup

Here was the technology I was working with as I went through this migration, for context:

| Computer | Make/Model | RAM | Hard Drive | OS |
|-----|-----|-----|-----|-----|
| **Source computer** | [MacBook Air (2015)](https://support.apple.com/en-us/112441) | 8GB | 128 GB | MacOS Big Sur |
| **Server** | [HP ProBook 640 G1](https://icecat.biz/p/hp/h5g66et/probook-notebooks-0888182270424-640+g1-20694735.html) | 16 GB (upgraded) | 500 GB |Arch Linux |

While I've tried to not leave Windows users out in the cold on this one, my experience, as you can see, is with a Mac, migrating to a Linux system, so that's what this guide will work best for.

## The Process

### Step 1 &mdash; Download your entire library to an external drive (on the source computer)

1. From the top bar, select **View > Show Status Bar**. This will add a bar at the bottom of the window with the size of your library in term of computer memory (GB, MB, etc.). Make sure your disk has at least this much space.

2. Point your iTunes library folder to your external drive by going into **Preferences > Files**, and selecting **"Choose Folder"** to the right of the box with the current filepath. 

3. Make sure **"Keep Files Organized" is checked**; this gives the downloads a reliable directory structure we'll need later.

4. Select all songs in your library, right-click, then hit **Download**. This could take a long time: on my MacBook Air, songs downloaded at a rate of about 50 songs/min, so it took around 3 hours to download the over 10k songs I had.

### Step 2 &mdash; Export your library

1. Export your iTunes library by selecting **File > Library > Export Library...** 

2. Copy this XML file (called `Library.xml` by default) onto the hard drive.

### Step 3 &mdash; Copy files to server

1. (You can skip this step if your server has the same OS type and version as your source machine). Check the **filesystem type on your external hard drive**. On a Mac, this can be seen by bringing up your drive on the Disk Utility app. The filesystem name will be next to the name of your drive. Older Macs tend to have a HFS+ filesystem (Hierarchical File System Plus), while newer ones tend to have APFS filesystems (Apple File System). 

2. **Eject the drive** from the source. Make sure this completes.

3. **Mount the drive** on the server. If you don't encounter any issues doing this, skip to the next step. Otherwise, make sure you're using a utility that can interpret the drive's filesystem into your server's filesystem. The drive may not be formatted in a way the server's OS can understand. First check the file system on your drive (on a Mac you would use the Disk Utility app). Once you've identified the file system, and its either HFS+ or APFS, try some of these resources:
    - [HFS+ to Linux](https://superuser.com/questions/84446/how-to-mount-a-hfs-partition-in-ubuntu-as-read-write) (for Ubuntu, but should point you in the right direction for your distro)
    - [HFS+ to Windows](https://www.provideocoalition.com/use-mac-drive-on-pc/)
    - [APFS to Linux](https://github.com/sgan81/apfs-fuse) (it's a GitHub repo; have fun!)
    - [APFS to Windows](https://www.paragon-software.com/home/apfs-windows/)

4. **Copy the files** into a directory of your choice on the server.


### Step 4 &mdash; Install Jellyfin

For this step, see [Jellyfin's installation guide](https://jellyfin.org/docs/general/installation/) for instructions for your server setup.

Since Jellyfin runs its commands, not as your user, but as a user called `jellyfin`, you need to give the `jellyfin` user access to your music. If you're on Linux/Mac, it works best if do the following:

1. Add the user `jellyfin` to the group with your username:

    ```
    sudo gpasswd --add jellyfin $USER
    ```

2. Give `jellyfin` user ownership of your media directory, and set the owning group to your user's group:

    ```
    sudo chown -R jellyfin:$USER <your media directory>
    ```

3. Allow your group read/write access to the media directory:

    ```
    sudo chmod -R g+rw <your media directory>
    ```

You'll also want the web client, as that gives you a nice GUI for Jellyfin, accessible through your browser. The rest of the steps assume you are using the web client.

### Step 5 &mdash; Add music and playlists to Jellyfin

1. **Make a playlist through Jellyfin**. You can do so by finding a song, clicking the **triple-dot** icon, and selecting **Add to Playlist** from the menu, and fill out the relevant information. 

3. **Find the playlist** you made, then click the **triple-dot**, and go to **Edit Metadata...**, and note down what the Path to the playlist is. The parent folder of the folder at the end of the path is where all your playlists should be placed (more on that shortly). If you're using a Docker container, the directory we need is the local one *outside* the container, not the path from within the container. I'll call this directory `playlist_dir` below.

### Step 6 &mdash; Convert your playlists

1. On your command line, **clone this repo**, and enter the cloned directory:
    ```
    git clone https://github.com/lmr97/itunes-to-jellyfin/
    cd itunes-to-jellyfin
    ```

2. **Install the conversion utility** 

    This is how to do so for a Linux machine (no root privileges required!): 
    
    1. Make a Python virtual environment named `pv` in current directory:
        ```
        python3 -m venv ./pv
        ```
    
    2. Install conversion utility (`itxml2pl`) into the virtual environment:
        ```
        ./pv/bin/pip install ./itxml2pl
        ```
    
    3. Creat [symbolic link](https://en.wikipedia.org/wiki/Symbolic_link) to the non-privileged part of [`$PATH`](https://en.wikipedia.org/wiki/PATH_(variable))
        ```
        ln -s "$PWD/pv/bin/itxml2pl" ~/.local/bin/itxml2pl
        ```

3. Now you can **run the playlist conversion program**:
    ```
    itxml2pl \
        -x <path to Library.xml> \
        -m <path to music dir on server> \
        [-d <path to music within Docker container>]
        -p playlist_dir \
    ```
    
    #### Usage notes

    `itxml2pl` will generate relative paths in the playlist files if the `-m` option is omitted. `-p` is also technically optional, and if omitted will place the playlist files in a folder called "Playlists" in the current working directory. If your server is running Windows, add `-w` to the command to use DOS filepaths. 
    
    You can run `itxml2pl --help` to see all available options. 

    #### For Jellyfin running in a Docker container

    If you're running your Jellyfin server from a **Docker** container, I should tell you that this program only supports containers that used [bind-mounted](https://stackoverflow.com/questions/47150829/what-is-the-difference-between-binding-mounts-and-volumes-while-handling-persist) directories for configuration and media directories, not volumes. If you're using volumes, you'll probably need to find another solution (maybe you use this program if you can install and run it inside the container, although I haven't tried that). 
    
    But if you're using bind mounts, you can add the `-d` option with the path to your music *from within the container*. So, for instance, if you store your music in `/media/Music`, and that directory is bind-mounted on `/Music` in the Docker container, then the argument you'd invoke the program as `itxml2pl -m /media/Music -d /Music <other args>`. `playlist_dir` is the path on your source computer's file system, regardless of whether Jellyfin is running from a container or not. 


### Step 7 &mdash; Rescan library

You need to have access to Jellyfin administration tools for this. To rescan library: 

1. Click the [hamburger](https://en.wikipedia.org/wiki/Hamburger_button)

2. Click **Dashboard** 

3. Click **Rescan All Libraries**. 
    
If you've already scanned your library before (which has probably already been done as a part of the Jellyfin install process), then this will be fairly quick.

## Syncing later downloads

If you end up downloading more music on your source computer that you would like in your Jellyfin library, and you're on a Unix-like system, `rsync` will work just fine. Something like this will do:

```
rsync -r --progress <path to source music directory> <user@remote-host:/path/to/music/dir>
```

It'll only add new files into the correct folders, creating them if necessary, but leave the ones you already have.

## Troubleshooting

If you have any issues with the process above, submit an issue on this repo, and I'll address it, and include the solution here below (if it's not an actual issue with the process, of course). 

### Other Jellyfin troubleshooting resources

- [ArchWiki's entry for Jellyfin](https://wiki.archlinux.org/title/Jellyfin#Troubleshooting): for Jellyfin instances running on Linux (non-Dockerized), and on Arch specifically

### Thanks for reading! I hope this helps with your great migration!