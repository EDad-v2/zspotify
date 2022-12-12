#! /usr/bin/env python3

"""
ZSpotify
It's like youtube-dl, but for Spotify.
"""

__version__ = "1.9.5"

import json
import os
import os.path
import platform
import re
import sys
import time
import shutil
from getpass import getpass
import datetime

import requests
from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
from librespot.core import Session
from librespot.metadata import TrackId, EpisodeId

from tqdm import tqdm
from appdirs import user_config_dir

# Change to True to use mutagen directly rather than through music_tag layer.
USE_MUTAGEN = True

if USE_MUTAGEN:
    from mutagen.id3 import ID3, TPE1, TIT2, TRCK, TALB, APIC, TPE2, TDRC, TDOR, TPOS, COMM, TCON
    from mutagen.oggvorbis import OggVorbis
    from mutagen.flac import Picture
    import base64

else:
    import music_tag

USE_FFMPEG = True  # Use system ffmpeg for encoding or copying raw vorbis streams into proper ogg containers.
if USE_FFMPEG:
    import ffmpeg
else:
    from pydub import AudioSegment


SESSION: Session = None
sanitize = ["\\", "/", ":", "*", "?", "'", "<", ">", '"']


CONFIG_DIR = user_config_dir("ZSpotify")
ROOT_PATH = os.path.expanduser("~/Music/ZSpotify Music/")
ROOT_PODCAST_PATH = os.path.expanduser("~/Music/ZSpotify Podcasts/")
ALBUM_IN_FILENAME = True # Puts album name in filename, otherwise name is (artist) - (track name).
REALTIME_WAIT = False
SKIP_EXISTING_FILES = True
SKIP_PREVIOUSLY_DOWNLOADED = True
MUSIC_FORMAT = os.getenv('MUSIC_FORMAT') or "mp3" # "mp3" | "ogg"
USE_VBR = True # Encodes mp3 with variable bitrate, for smaller sizes. Does not affect ogg
FORCE_PREMIUM = False # set to True if not detecting your premium account automatically
RAW_AUDIO_AS_IS = False # set to False if you wish you save the raw audio without re-encoding it.
if os.getenv('RAW_AUDIO_AS_IS') != None and os.getenv('RAW_AUDIO_AS_IS') != "y":
    RAW_AUDIO_AS_IS = False
# This is how many seconds ZSpotify waits between downloading tracks so spotify doesn't get out the ban hammer
ANTI_BAN_WAIT_TIME = 5
ANTI_BAN_WAIT_TIME_ALBUMS = 30
# Set this to True to not wait at all between tracks and just go balls to the wall
OVERRIDE_AUTO_WAIT = False
CHUNK_SIZE = 50000

CREDENTIALS = os.path.join(CONFIG_DIR, "credentials.json")
LIMIT = 50 

requests.adapters.DEFAULT_RETRIES = 10
REINTENT_DOWNLOAD = 30
IS_PODCAST = False
ALBUM_DIR_SHORT = True
SPLIT_ALBUM_CDS = False
PLAYLIST_SONG_ALBUMS = False
MULTI_CDS = False # not for humans to change!
genre_cache = dict()
CUSTOM_NAMING = False

# miscellaneous functions for general use


def clear():
    """ Clear the console window """
    if platform.system() == "Windows":
        os.system("cls")
    else:
        os.system("clear")


def wait(seconds: int = 3):
    """ Pause for a set number of seconds """
    for i in range(seconds)[::-1]:
        print("\rWait for %d second(s)..." % (i + 1), end="")
        time.sleep(1)


def antiban_wait():
    """ Pause between albums for a set number of seconds """
    for i in range(ANTI_BAN_WAIT_TIME_ALBUMS)[::-1]:
        print("\rWait for Next Download in %d second(s)..." % (i + 1), end="")
        time.sleep(1)


def convert_seconds(seconds):
    seconds = seconds % (24 * 3600)
    hour = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds %= 60
        
    return "%d:%02d:%02d" % (hour, minutes, seconds)       


def realtime_wait(realtime_started, duration_ms, total_size, downloaded):
    time_start = realtime_started
    delta_real = time.time() - time_start
    delta_want = (downloaded / total_size) * (duration_ms/1000)
    if delta_want > delta_real:
        #need_wait = int(delta_want - delta_real)
        time.sleep(delta_want - delta_real)


def sanitize_data(value):
    """ Returns given string with probl/ematic removed """
    #global sanitize
    if "AC/DC" in value:
        value = value.replace("/", "⚡") # replace forward slash with ⚡

    for i in sanitize:
        value = value.replace(i, "")
    return value.replace("|", "-")


def split_input(selection):
    """ Returns a list of inputted strings """
    if "-" in selection:
        return [i for i in range(int(selection.split("-")[0]),int(selection.split("-")[1]+1))] 
    else:
        return [i for i in selection.strip().split(" ")]


def splash():
    """ Displays splash screen """
    print("""
███████ ███████ ██████   ██████  ████████ ██ ███████ ██    ██
   ███  ██      ██   ██ ██    ██    ██    ██ ██       ██  ██
  ███   ███████ ██████  ██    ██    ██    ██ █████     ████
 ███         ██ ██      ██    ██    ██    ██ ██         ██
███████ ███████ ██       ██████     ██    ██ ██         ██
    """)
    print(f"version: {__version__}")


# two mains functions for logging in and doing client stuff
def login():
    """ Authenticates with Spotify and saves credentials to a file """
    global SESSION

    if os.path.isfile(CREDENTIALS):
        try:
            conf = Session.Configuration.Builder().set_stored_credential_file(CREDENTIALS).set_store_credentials(False).build()
            SESSION = Session.Builder(conf).stored_file().create()
            return
        except BaseException as e:

            print("\n\nLogin error! Is your stored credential file corrupt?\n")
            print("Hopefully re-logging will resolve this.\n")
            print(f"Delete {CREDENTIALS} file if error persists.\n")
            print(f"[!] ERROR {e} \n")
    while True:
        user_name = input("Username: ")
        password = getpass()
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            conf = Session.Configuration.Builder().set_stored_credential_file(CREDENTIALS).build()
            SESSION = Session.Builder(conf).user_pass(user_name, password).create()
            return
        except BaseException as e:
            print(f"Login error, Username or Pass incorrect?\n[!] ERROR {e} \n")


def client():
    """ Connects to spotify to perform query's and get songs to download """
    global QUALITY, SESSION, REALTIME_WAIT, PLAYLIST_SONG_ALBUMS, SPLIT_ALBUM_CDS, CUSTOM_NAMING, CUSTOM_PATH
    splash()
    CUSTOM_PATH = False
    CUSTOM_NAMING = False

    token = SESSION.tokens().get("user-read-email")
    token_for_saved = SESSION.tokens().get("user-library-read")

    if check_premium():
        print("[ DETECTED PREMIUM ACCOUNT - USING VERY_HIGH QUALITY ]\n\n")
        QUALITY = AudioQuality.VERY_HIGH
    else:
        print("[ DETECTED FREE ACCOUNT - USING HIGH QUALITY ]\n\n")
        QUALITY = AudioQuality.HIGH

    for arg in sys.argv:
        if arg == '-rt' or arg == '--realtime':
            REALTIME_WAIT = True
        if arg == '-dpa' or arg == '--download_playlist_albums':
            PLAYLIST_SONG_ALBUMS = True
        if arg == '-split' or arg == '--split_album_cds':
            SPLIT_ALBUM_CDS = True
        if arg == '-o' or arg == '--out':
            arg_index = sys.argv.index(arg)
            try:
                if arg_index < len(sys.argv):             
                    CUSTOM_PATH = sys.argv[arg_index + 1]
                    CUSTOM_NAMING = True
            except:
                print(f'{arg} must be followed with a custom path string')
                print("\n\tExample: " + arg + " \"{ROOT_PATH}/{ARTIST}/{ALBUM}/{ARTIST} - {NAME}.{MUSIC_FORMAT}\"\n")
                print("\tString should be in quotes.")
                print("\nOutput path and filename unchanged.")

    if len(sys.argv) > 1:
        if sys.argv[1] == "-p" or sys.argv[1] == "--playlist":
            download_from_user_playlist()
        elif sys.argv[1] == "-pid" or sys.argv[1] == "--playlist_id":
            if len(sys.argv) > 3:
                download_playlist_by_id(sys.argv[2], sys.argv[3])
            else:
                print("With the flag playlist_id you must pass the playlist_id and the name of the folder where you will have the songs. Usually these name is the name of the playlist itself.")
        elif sys.argv[1] == "-ls" or sys.argv[1] == "--liked-songs":
            for song in get_saved_tracks(token_for_saved):
                if not song['track']['name']:
                    print(
                        "###   SKIPPING:  SONG DOES NOT EXISTS ON SPOTIFY ANYMORE   ###")
                else:
                    download_track(song['track']['id'], "Liked Songs/")
                print("\n")
        else:
            track_id_str, album_id_str, playlist_id_str, episode_id_str, show_id_str, artist_id_str = regex_input_for_urls(
                sys.argv[1])

            if track_id_str is not None:
                download_track(track_id_str)
            elif artist_id_str is not None:
                download_artist_albums(artist_id_str)
            elif album_id_str is not None:
                download_album(album_id_str)
            elif playlist_id_str is not None:
                name, creator = get_playlist_info(token, playlist_id_str) 
                download_playlist_by_id(playlist_id_str, sanitize_data(name)) # download_playlist_by_id(), can replace above
            elif episode_id_str is not None:
                download_episode(episode_id_str)
            elif show_id_str is not None:
                for episode in get_show_episodes(token, show_id_str):
                    download_episode(episode)

    else:
        search_text = input("Enter search or URL: ")

        track_id_str, album_id_str, playlist_id_str, episode_id_str, show_id_str, artist_id_str = regex_input_for_urls(
            search_text)

        if track_id_str is not None:
            download_track(track_id_str)
        elif artist_id_str is not None:
            download_artist_albums(artist_id_str)
        elif album_id_str is not None:
            download_album(album_id_str)
        elif playlist_id_str is not None:
            playlist_songs = get_playlist_songs(token, playlist_id_str)
            name, creator = get_playlist_info(token, playlist_id_str)
            for song in playlist_songs:
                download_track(song['track']['id'],
                               sanitize_data(name) + "/")
                print("\n")
        elif episode_id_str is not None:
            download_episode(episode_id_str)
        elif show_id_str is not None:
            for episode in get_show_episodes(token, show_id_str):
                download_episode(episode)
        else:
            try:
                search(search_text)
            except:
                client()
            client()

    # wait()


def regex_input_for_urls(search_input):
    track_uri_search = re.search(
        r"^spotify:track:(?P<TrackID>[0-9a-zA-Z]{22})$", search_input)
    track_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/track/(?P<TrackID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    album_uri_search = re.search(
        r"^spotify:album:(?P<AlbumID>[0-9a-zA-Z]{22})$", search_input)
    album_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/album/(?P<AlbumID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    playlist_uri_search = re.search(
        r"^spotify:playlist:(?P<PlaylistID>[0-9a-zA-Z]{22})$", search_input)
    playlist_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/playlist/(?P<PlaylistID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    episode_uri_search = re.search(
        r"^spotify:episode:(?P<EpisodeID>[0-9a-zA-Z]{22})$", search_input)
    episode_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/episode/(?P<EpisodeID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    show_uri_search = re.search(
        r"^spotify:show:(?P<ShowID>[0-9a-zA-Z]{22})$", search_input)
    show_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/show/(?P<ShowID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    artist_uri_search = re.search(
        r"^spotify:artist:(?P<ArtistID>[0-9a-zA-Z]{22})$", search_input)
    artist_url_search = re.search(
        r"^(https?://)?open\.spotify\.com/artist/(?P<ArtistID>[0-9a-zA-Z]{22})(\?si=.+?)?$",
        search_input,
    )

    if track_uri_search is not None or track_url_search is not None:
        track_id_str = (track_uri_search
                        if track_uri_search is not None else
                        track_url_search).group("TrackID")
    else:
        track_id_str = None

    if album_uri_search is not None or album_url_search is not None:
        album_id_str = (album_uri_search
                        if album_uri_search is not None else
                        album_url_search).group("AlbumID")
    else:
        album_id_str = None

    if playlist_uri_search is not None or playlist_url_search is not None:
        playlist_id_str = (playlist_uri_search
                           if playlist_uri_search is not None else
                           playlist_url_search).group("PlaylistID")
    else:
        playlist_id_str = None

    if episode_uri_search is not None or episode_url_search is not None:
        episode_id_str = (episode_uri_search
                          if episode_uri_search is not None else
                          episode_url_search).group("EpisodeID")
    else:
        episode_id_str = None

    if show_uri_search is not None or show_url_search is not None:
        show_id_str = (show_uri_search
                       if show_uri_search is not None else
                       show_url_search).group("ShowID")
    else:
        show_id_str = None

    if artist_uri_search is not None or artist_url_search is not None:
        artist_id_str = (artist_uri_search
                         if artist_uri_search is not None else
                         artist_url_search).group("ArtistID")
    else:
        artist_id_str = None

    return track_id_str, album_id_str, playlist_id_str, episode_id_str, show_id_str, artist_id_str


def get_episode_info(episode_id_str):
    token = SESSION.tokens().get("user-read-email")
    info = json.loads(requests.get("https://api.spotify.com/v1/episodes/" +
                                   episode_id_str, headers={"Authorization": "Bearer %s" % token}).text)

    sum_total = []
    for sum_px in info['images']:
        sum_total.append(sum_px['height'] + sum_px['width'])

    img_index = sum_total.index(max(sum_total))
    image_url = info['images'][img_index]['url']
    release_date = info["release_date"]
    scraped_episode_id = info['id']

    if "error" in info:
        return None, None
    else:
        return sanitize_data(info["show"]["name"]), sanitize_data(info["name"]), image_url, release_date, scraped_episode_id


def get_show_episodes(access_token, show_id_str):
    """ returns episodes of a show """
    episodes = []
    offset = 0
    limit = 50

    while True:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': limit, 'offset': offset}
        resp = requests.get(
            f'https://api.spotify.com/v1/shows/{show_id_str}/episodes', headers=headers, params=params).json()
        offset += limit
        for episode in resp["items"]:
            episodes.append(episode["id"])

        if len(resp['items']) < limit:
            break

    return episodes


def download_episode(episode_id_str):
    #global ROOT_PODCAST_PATH, MUSIC_FORMAT, RAW_AUDIO_AS_IS, SKIP_EXISTING_FILES, SKIP_PREVIOUSLY_DOWNLOADED, IS_PODCAST, META_GENRE
    global IS_PODCAST, META_GENRE
    IS_PODCAST = True
    META_GENRE = False

    podcast_name, episode_name, image_url, release_date, scraped_episode_id = get_episode_info(episode_id_str)
    check_all_time = episode_id_str in get_previously_downloaded()
    episode_filename = f'{podcast_name}-{episode_name}.{MUSIC_FORMAT}'
    filename = os.path.join(ROOT_PODCAST_PATH, podcast_name, episode_filename)
    tempfile = os.path.join(ROOT_PODCAST_PATH, podcast_name, episode_filename[:-4] + "-vorbis.raw")
 
    if podcast_name is None:
        print("###   SKIPPING: (EPISODE NOT FOUND)   ###")

    elif os.path.isfile(filename) and os.path.getsize(filename) and SKIP_EXISTING_FILES:
        print("###   SKIPPING: (EPISODE ALREADY EXISTS) :", episode_name, "   ###")

    elif check_all_time and SKIP_PREVIOUSLY_DOWNLOADED:
        print('###   SKIPPING: ' + episode_name + ' (EPISODE ALREADY DOWNLOADED ONCE)   ###')

    else:
        episode_id = EpisodeId.from_base62(episode_id_str)
        stream = SESSION.content_feeder().load(
            episode_id, VorbisOnlyAudioQuality(QUALITY), False, None)

        os.makedirs(os.path.join(ROOT_PODCAST_PATH, podcast_name),exist_ok=True)

        total_size = stream.input_stream.size
        data_left = total_size
        downloaded = 0
        _CHUNK_SIZE = CHUNK_SIZE
        fail = 0
        bar_txt = episode_name
        if REALTIME_WAIT:
            bar_txt = "\033[1;37;44m REALTIME \033[m " + bar_txt

        with open(tempfile, 'wb') as file, tqdm(
                desc=bar_txt,
                total=total_size,
                unit='B',
                unit_scale=True,
                unit_divisor=1024
        ) as bar:
            while downloaded <= total_size:
                data = stream.input_stream.stream().read(_CHUNK_SIZE)
                downloaded += len(data)
                bar.update(file.write(data))
                if (total_size - downloaded) < _CHUNK_SIZE:
                    _CHUNK_SIZE = total_size - downloaded
                #print(f"[{total_size}][{_CHUNK_SIZE}] [{len(data)}] [{total_size - downloaded}] [{downloaded}]")
                if len(data) == 0 : 
                    fail += 1
                if fail > REINTENT_DOWNLOAD:
                    break

            file.close() # Windoze needs.

            convert_audio_format(tempfile, filename)
            if not RAW_AUDIO_AS_IS:
                if USE_MUTAGEN:
                    set_audio_tags_mutagen(filename, "", episode_name, podcast_name, release_date, "", "", scraped_episode_id, image_url)
                else:
                    set_audio_tags(filename, "", episode_name, podcast_name, release_date, 0, 0, scraped_episode_id)
                    set_music_thumbnail(filename, image_url)

            add_to_archive(episode_id_str, filename, podcast_name, episode_name)
            IS_PODCAST = False


def search(search_term):
    """ Searches Spotify's API for relevant data """
    token = SESSION.tokens().get("user-read-email")

    resp = requests.get(
        "https://api.spotify.com/v1/search",
        {
            "limit": LIMIT,
            "offset": "0",
            "q": search_term,
            "type": "track,album,playlist,artist"
        },
        headers={"Authorization": "Bearer %s" % token},
    )
    #print("token: ",token)

    i = 1
    tracks = resp.json()["tracks"]["items"]
    if len(tracks) > 0:
        print("###  TRACKS  ###")
        for track in tracks:
            if track["explicit"]:
                explicit = "[E]"
            else:
                explicit = ""
            print(f"{i}, {track['name']} {explicit} | {','.join([artist['name'] for artist in track['artists']])}")
            i += 1
        total_tracks = i - 1
        print("\n")
    else:
        total_tracks = 0

    albums = resp.json()["albums"]["items"]
    if len(albums) > 0:
        print("###  ALBUMS  ###")
        for album in albums:
            #print("==>",album,"\n")
            _year = re.search('(\d{4})', album['release_date']).group(1)
            print(f"{i}, ({_year}) {album['name']} [{album['total_tracks']}] | {','.join([artist['name'] for artist in album['artists']])}" )
            i += 1
        total_albums = i - total_tracks - 1
        print("\n")
    else:
        total_albums = 0

    playlists = resp.json()["playlists"]["items"]
    total_playlists = 0
    print("###  PLAYLISTS  ###")
    for playlist in playlists:
        print(f"{i}, {playlist['name']} | {playlist['owner']['display_name']}" )
        i += 1
    total_playlists = i - total_albums - total_tracks  - 1
    print("\n")

    artists = resp.json()["artists"]["items"]
    total_artists = 0
    print("###  ARTIST  ###")
    for artist in artists:
        #print("==> ",artist)
        print(f"{i}, {artist['name']} | {'/'.join(artist['genres'])}") 
        i += 1
    total_artists = i - total_albums - total_tracks - total_playlists - 1
    print("\n")

    if len(tracks) + len(albums) + len(playlists) == 0:
        print("NO RESULTS FOUND - EXITING...")
    else:

        selection = str(input("SELECT ITEM(S) BY ID: "))
        inputs = split_input(selection)
        
        if not selection: client()
        
        for pos in inputs:
            position = int(pos)
            if position <= total_tracks:
                track_id = tracks[position - 1]["id"]
                download_track(track_id)
            elif position <= total_albums + total_tracks:
                #print("==>" , position , " total_albums + total_tracks ", total_albums + total_tracks )
                download_album(albums[position - total_tracks - 1]["id"])
            elif position <= total_albums + total_tracks + total_playlists:
                #print("==> position: ", position ," total_albums + total_tracks + total_playlists ", total_albums + total_tracks + total_playlists )
                playlist_choice = playlists[position -
                                            total_tracks - total_albums - 1]
                playlist_songs = get_playlist_songs(token, playlist_choice['id'])
                for song in playlist_songs:
                    if song['track']['id'] is not None:
                        download_track(song['track']['id'], sanitize_data(
                            playlist_choice['name'].strip()) + "/")
                        print("\n")
            else:
                #5eyTLELpc4Coe8oRTHkU3F
                #print("==> position: ", position ," total_albums + total_tracks + total_playlists: ", position - total_albums - total_tracks - total_playlists )
                artists_choice = artists[position - total_albums - total_tracks - total_playlists - 1]
                albums = get_albums_artist(token,artists_choice['id'])
                i=0

                print("\n")
                print("ALL ALBUMS: ",len(albums)," IN:",str(set(album['album_type'] for album in albums)))
                
                for album in albums:
                    if artists_choice['id'] == album['artists'][0]['id'] and album['album_type'] != 'single':
                        i += 1
                        year = re.search('(\d{4})', album['release_date']).group(1)
                        print(f" {i} {album['artists'][0]['name']} - ({year}) {album['name']} [{album['total_tracks']}] [{album['album_type']}]")
                total_albums_downloads = i
                print("\n")

                #print('\n'.join([f"{album['name']} - [{album['album_type']}] | {'/'.join([artist['name'] for artist in album['artists']])} " for album in sorted(albums, key=lambda k: k['album_type'], reverse=True)]))

                
                for i in range(8)[::-1]:
                    print("\rWait for Download in %d second(s)..." % (i + 1), end="")
                    time.sleep(1)
                
                print("\n")
                i=0
                for album in albums:
                    if artists_choice['id'] == album['artists'][0]['id'] and album['album_type'] != 'single' :
                        i += 1
                        year = re.search('(\d{4})', album['release_date']).group(1)
                        print(f"\n\n\n{i}/{total_albums_downloads} {album['artists'][0]['name']} - ({year}) {album['name']} [{album['total_tracks']}]")
                        download_album(album['id'])
                        antiban_wait()


def get_artist_info(artist_id):
    """ Retrieves metadata for downloaded songs """
    token = SESSION.tokens().get("user-read-email")
    try:
        info = json.loads(requests.get("https://api.spotify.com/v1/artists/" + artist_id, headers={"Authorization": "Bearer %s" % token}).text)
        return info
    except Exception as e:
        print("###   get_artist_info - FAILED TO QUERY METADATA   ###")
        print(e)
        print(artist_id,info)


def lookup_genre(artist_id):
    '''get genre by artist_id from API'''
    info = get_artist_info(artist_id)    
    return conv_artist_format(info['genres'])


def get_genre(artist_id):
    '''return cached genre, else lookup, cache and return'''
    if artist_id not in genre_cache:
        genre_cache[artist_id] = lookup_genre(artist_id)

    return genre_cache[artist_id] # 


def get_song_info(song_id):
    """ Retrieves metadata for downloaded songs """
    token = SESSION.tokens().get("user-read-email")
    try:

        info = json.loads(requests.get("https://api.spotify.com/v1/tracks?ids=" + song_id +
                        '&market=from_token', headers={"Authorization": "Bearer %s" % token}).text)

        #Sum the size of the images, compares and saves the index of the largest image size
        sum_total = []
        for sum_px in info['tracks'][0]['album']['images']:
            sum_total.append(sum_px['height'] + sum_px['width'])

        img_index = sum_total.index(max(sum_total))
        
        artist_id = info['tracks'][0]['artists'][0]['id']
        artists = []
        for data in info['tracks'][0]['artists']:
            artists.append(sanitize_data(data['name']))
        album_name = sanitize_data(info['tracks'][0]['album']["name"])
        name = sanitize_data(info['tracks'][0]['name'])
        image_url = info['tracks'][0]['album']['images'][img_index]['url']
        release_year = info['tracks'][0]['album']['release_date'].split("-")[0]
        disc_number = info['tracks'][0]['disc_number']
        track_number = info['tracks'][0]['track_number']
        scraped_song_id = info['tracks'][0]['id']
        is_playable = info['tracks'][0]['is_playable']
        duration_ms = info['tracks'][0]['duration_ms']

        return artists, album_name, name, image_url, release_year, disc_number, track_number, scraped_song_id, is_playable, artist_id, duration_ms
    except Exception as e:
        print("###   get_song_info - FAILED TO QUERY METADATA   ###")
        print(e)
        print(song_id,info)

def check_premium():
    """ If user has spotify premium return true """
    #global FORCE_PREMIUM
    return bool((SESSION.get_user_attribute("type") == "premium") or FORCE_PREMIUM)


# Functions directly related to modifying the downloaded audio and its metadata
def convert_audio_format(fromfilename, tofilename):
    """ Converts raw audio into playable mp3 or ogg vorbis """
    #global MUSIC_FORMAT
    #global USE_VBR
    if not USE_FFMPEG:
        '''Use pydub and ffmpeg to encode to wav, then to mp3 or ogg'''
        raw_audio = AudioSegment.from_file(fromfilename, format="ogg",
                                        frame_rate=44100, channels=2, sample_width=2)
        if QUALITY == AudioQuality.VERY_HIGH:
            bitrate = "0" if MUSIC_FORMAT == "mp3" and USE_VBR else "320k" # VBR 0 ~= 320kbps for MP3
        else:
            bitrate = "4" if MUSIC_FORMAT == "mp3" and USE_VBR else "160k" # VBR 4 ~= 160kbps for MP3
        bitrateFlag = "-q:a" if USE_VBR and MUSIC_FORMAT == "mp3" else "-b:a" # VBR and CBR use different ffmpeg flags
        raw_audio.export(tofilename, format=MUSIC_FORMAT, parameters=[bitrateFlag, bitrate])

    else:
        '''Use ffmpeg-python to encode to mp3. If ogg, copy raw stream into ogg container.'''
        if MUSIC_FORMAT == "mp3":
            if QUALITY == AudioQuality.VERY_HIGH:
                bitrate = "0" if USE_VBR else "320k"
            else:
                bitrate = "4" if USE_VBR else "160k"
            if USE_VBR:
                (
                    ffmpeg
                    .input(fromfilename)
                    .output(tofilename, acodec='libmp3lame', aq=bitrate)
                    .global_args('-loglevel', 'quiet')
                    .run()
                )
            else: # There's probably a better way to do this
                (
                    ffmpeg
                    .input(fromfilename)
                    .output(tofilename, acodec='libmp3lame')
                    .global_args('-loglevel', 'quiet')
                    .run()
                )

        elif MUSIC_FORMAT == "ogg": # No bitrate parameters are needed - just copying data
            (
                ffmpeg
                .input(fromfilename)
                .output(tofilename, acodec='copy')
                .global_args('-loglevel', 'quiet')
                .run()
            )

    if not RAW_AUDIO_AS_IS:
        if os.path.exists(fromfilename):
            os.remove(fromfilename)

def encode_ogg_coverart(art_url, desc):
    picture = Picture()
    picture.data = requests.get(art_url).content
    #picture.type = 17
    picture.type = 3
    picture.desc = u'' + desc + ''
    picture.mime = u"image/jpeg"
    picture.width = 640
    picture.height = 640
    picture.depth = 24
    picture_data = picture.write()
    encoded_data = base64.b64encode(picture_data)
    #vcomment_value = encoded_data.decode("ascii")
    return encoded_data.decode("ascii")


def set_audio_tags(filename, artists, name, album_name, release_year, disc_number, track_number, track_id_str):
    """ sets music_tag metadata """
    #print("###   SETTING MUSIC TAGS   ###")
    tags = music_tag.load_file(filename)
    tags['artist'] = conv_artist_format(artists)
    tags['tracktitle'] = name
    tags['album'] = album_name
    tags['year'] = release_year
    tags['discnumber'] = disc_number
    tags['tracknumber'] = track_number
    tags['comment'] = 'id[spotify.com:track:'+track_id_str+']'
    tags.save()


def set_audio_tags_mutagen(filename, artists, name, album_name, release_year, disc_number, track_number, track_id_str, image_url):
    """ sets music_tag metadata using mutagen """
    artist = conv_artist_format(artists)
    check_various_artists = "Various Artists" in filename
    if check_various_artists:
        album_artist = "Various Artists"
    else:
        album_artist = artist

    if IS_PODCAST:
        track_id_str = "id[spotify.com:show:" + track_id_str + "]"
    else:
        track_id_str = "id[spotify.com:track:" + track_id_str + "]"
    
    genre = "Unknown"
    if META_GENRE:
        genre = META_GENRE

    if MUSIC_FORMAT == "mp3":
        tags = ID3(filename)
        tags['TPE1'] = TPE1(encoding=3, text=artist)             # TPE1 Lead Artist/Performer/Soloist/Group
        tags['TIT2'] = TIT2(encoding=3, text=name)               # TIT2 Title/songname/content description
        tags['TALB'] = TALB(encoding=3, text=album_name)         # TALB Album/Movie/Show title
        tags['TDRC'] = TDRC(encoding=3, text=release_year)       # TDRC Recording time
        tags['TDOR'] = TDOR(encoding=3, text=release_year)       # TDOR Original release time
        tags['TPOS'] = TPOS(encoding=3, text=str(disc_number))   # TPOS Part of a set
        tags['TRCK'] = TRCK(encoding=3, text=str(track_number))  # TRCK Track number/Position in set
        tags['COMM'] = COMM(encoding=3, lang=u'eng', text=u'' + track_id_str + '') #COMM User comment
        tags['TPE2'] = TPE2(encoding=3, text=album_artist)       # TPE2 Band/orchestra/accompaniment
        tags['APIC'] = APIC(                                     # APIC Attached (or linked) Picture.
                            encoding=3,
                            mime='image/jpeg',
                            type=3,
                            desc=u'' + album_name,
                            data=requests.get(image_url).content)
        tags['TCON'] = TCON(encoding=3, text=genre)              # TCON Genre
        tags.save()

    elif MUSIC_FORMAT == "ogg":
        tags = OggVorbis(filename)        
        #tags.delete() # clear metadata and start fresh        
        tags['TITLE'] = name 
        tags['ARTIST'] = artist
        tags['TRACKNUMBER'] = str(track_number)
        tags['DISCNUMBER'] = str(disc_number)
        tags['ALBUM'] = album_name
        tags['ALBUMARTIST'] = album_artist
        tags['DATE'] = release_year
        tags['GENRE'] = genre
        tags['COMMENT'] = u'id[spotify.com:track:'+track_id_str+']'
        tags['METADATA_BLOCK_PICTURE'] = [encode_ogg_coverart(image_url, album_name)]
        tags.save()


def set_music_thumbnail(filename, image_url):
    """ Downloads cover artwork """
    #print("###   SETTING THUMBNAIL   ###")
    img = requests.get(image_url).content
    tags = music_tag.load_file(filename)
    tags['artwork'] = img
    tags.save()


def conv_artist_format(artists):
    """ Returns converted artist format """
    formatted = ""
    for artist in artists:
        formatted += artist + ", "
    return formatted[:-2]


# Extra functions directly related to spotify playlists
def get_all_playlists(access_token):
    """ Returns list of users playlists """
    playlists = []
    limit = 50
    offset = 0

    while True:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': limit, 'offset': offset}
        resp = requests.get("https://api.spotify.com/v1/me/playlists",
                            headers=headers, params=params).json()
        offset += limit
        playlists.extend(resp['items'])

        if len(resp['items']) < limit:
            break

    return playlists


def get_playlist_songs(access_token, playlist_id):
    """ returns list of songs in a playlist """
    songs = []
    offset = 0
    limit = 100

    while True:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': limit, 'offset': offset}
        resp = requests.get(
            f'https://api.spotify.com/v1/playlists/{playlist_id}/tracks', headers=headers, params=params).json()
        offset += limit
        songs.extend(resp['items'])

        if len(resp['items']) < limit:
            break

    return songs


def get_playlist_info(access_token, playlist_id):
    """ Returns information scraped from playlist """
    headers = {'Authorization': f'Bearer {access_token}'}
    resp = requests.get(
        f'https://api.spotify.com/v1/playlists/{playlist_id}?fields=name,owner(display_name)&market=from_token', headers=headers).json()
    return resp['name'].strip(), resp['owner']['display_name'].strip()


# Extra functions directly related to spotify albums
def get_album_tracks(access_token, album_id):
    """ Returns album tracklist """
    songs = []
    offset = 0
    limit = 50
    include_groups = 'album,compilation'

    while True:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': limit, 'include_groups':include_groups, 'offset': offset}
        resp = requests.get(
            f'https://api.spotify.com/v1/albums/{album_id}/tracks', headers=headers, params=params).json()
        offset += limit
        songs.extend(resp['items'])

        if len(resp['items']) < limit:
            break

    return songs


def get_album_name(access_token, album_id):
    """ Returns album name """
    headers = {'Authorization': f'Bearer {access_token}'}
    resp = requests.get(
        f'https://api.spotify.com/v1/albums/{album_id}', headers=headers).json()
    
    #_yearalbum = re.search('(\d{4})', resp['release_date']).group(1)
    #print(f"\n {resp['name']} - {_yearalbum} [{resp['total_tracks']}]")

    if m := re.search('(\d{4})', resp['release_date']):
        return resp['artists'][0]['name'], m.group(1),sanitize_data(resp['name']),resp['total_tracks']
    else: return resp['artists'][0]['name'], resp['release_date'],sanitize_data(resp['name']),resp['total_tracks']


def get_artist_albums(access_token, artists_id):
    """ Returns artist's albums """

    albums = []
    offset = 0
    limit = 50
    include_groups = 'album,compilation'

    while True:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': limit, 'include_groups': include_groups, 'offset': offset}

        resp = requests.get(
            f'https://api.spotify.com/v1/artists/{artists_id}/albums', headers=headers, params=params).json()

        offset += limit
        albums.extend(resp['items'])

        if len(resp['items']) < limit:
            break
    return albums

# Extra functions directly related to our saved tracks


def get_saved_tracks(access_token):
    """ Returns user's saved tracks """
    songs = []
    offset = 0
    limit = 50

    while True:
        headers = {'Authorization': f'Bearer {access_token}'}
        params = {'limit': limit, 'offset': offset}
        resp = requests.get('https://api.spotify.com/v1/me/tracks',
                            headers=headers, params=params).json()
        offset += limit
        songs.extend(resp['items'])

        if len(resp['items']) < limit:
            break

    return songs

def get_previously_downloaded() -> list[str]:
    """ Returns list of all time downloaded songs, sourced from the hidden archive file located at the download
    location. """
    #global ROOT_PATH, ROOT_PODCAST_PATH

    ids = []
    if not IS_PODCAST:
        archive_path = os.path.join(ROOT_PATH, '.song_archive')
    else:
        archive_path = os.path.join(ROOT_PODCAST_PATH, '.episode_archive')

    if os.path.exists(archive_path):
        with open(archive_path, 'r', encoding='utf-8') as f:
            ids = [line.strip().split('\t')[0] for line in f.readlines()]

    return ids

def add_to_archive(song_id: str, filename: str, author_name: str, song_name: str) -> None:
    """ Adds song id to all time installed songs archive """
    archive_path = ""
    if not IS_PODCAST:
        archive_path = os.path.join(os.path.dirname(__file__), ROOT_PATH, '.song_archive')
    else:
        archive_path = os.path.join(os.path.dirname(__file__), ROOT_PODCAST_PATH, '.episode_archive')

    if os.path.exists(archive_path):
        with open(archive_path, 'a', encoding='utf-8') as file:
            file.write(f'{song_id}\t{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\t{author_name}\t{song_name}\t{filename}\n')
    else:
        with open(archive_path, 'w', encoding='utf-8') as file:
            file.write(f'{song_id}\t{datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}\t{author_name}\t{song_name}\t{filename}\n')


# Functions directly related to downloading stuff
def download_track(track_id_str: str, extra_paths="", prefix=False, prefix_value='', disable_progressbar=False):
    """ Downloads raw song audio from Spotify """
    #global ROOT_PATH, SKIP_EXISTING_FILES, SKIP_PREVIOUSLY_DOWNLOADED, MUSIC_FORMAT, RAW_AUDIO_AS_IS, ANTI_BAN_WAIT_TIME, OVERRIDE_AUTO_WAIT, ALBUM_IN_FILENAME, META_GENRE
    global META_GENRE
    META_GENRE = False    
    try:
    	# TODO: ADD disc_number IF > 1 
        artists, album_name, name, image_url, release_year, disc_number, track_number, scraped_song_id, is_playable, artist_id, duration_ms = get_song_info(
            track_id_str)

        #info = get_artist_info(artist_id)
        #genre = conv_artist_format(info['genres'])
        genre = get_genre(artist_id)
 
        _artist = artists[0]
        if not SPLIT_ALBUM_CDS and MULTI_CDS:
            _track_number = str(disc_number) + str(track_number).zfill(2)
        else:
            _track_number = str(track_number).zfill(2)

        if CUSTOM_NAMING:
            if "{ROOT_PATH}" in CUSTOM_PATH:
                join_root_path = True

            # Remove after testing
            # MUSIC_FORMAT=ogg python zspotify.py https://open.spotify.com/album/4vu7F6h90Br1ZtYYaqfITy -o "{ROOT_PATH}/{ARTIST}/{ALBUM} ({YEAR})/{TRACK} - {TITLE}.{EXT}"
            song_name2 = CUSTOM_PATH.format(ROOT_PATH = '',
                                           ARTIST = _artist,
                                           ALBUM = album_name,
                                           TITLE = name,
                                           YEAR = release_year,
                                           DISC = disc_number,
                                           TRACK = _track_number,
                                           EXT = MUSIC_FORMAT
                                           )
            song_name2 = song_name2.split("/")
            if not join_root_path:
                song_name2 = os.path.join(*song_name2)
            else:
                song_name2 = os.path.join(ROOT_PATH, *song_name2)

            print("Test song name: ", song_name2)
        
        else:
            print("Custom naming isn't active")
         
        if prefix:
            _track_number = str(track_number).zfill(2)
            #song_name = f'{_artist} - {album_name} - {_track_number}. {name}.{MUSIC_FORMAT}' 
            song_name = f'{_track_number} - {name}.{MUSIC_FORMAT}' 
            filename = os.path.join(ROOT_PATH, extra_paths, song_name) 
        elif ALBUM_IN_FILENAME:
            song_name = f'{_artist} - {album_name} - {name}.{MUSIC_FORMAT}'
            filename = os.path.join(ROOT_PATH, extra_paths, song_name)
        else:
            song_name = f'{_artist} - {name}.{MUSIC_FORMAT}'
            filename = os.path.join(ROOT_PATH, extra_paths, song_name)

        if prefix and not SPLIT_ALBUM_CDS and MULTI_CDS:
            _track_number = str(disc_number) + str(track_number).zfill(2)
            song_name = f'{_track_number} - {name}.{MUSIC_FORMAT}' 
            filename = os.path.join(ROOT_PATH, extra_paths, song_name)

        check_all_time = scraped_song_id in get_previously_downloaded()
        tempfile = os.path.join(ROOT_PATH, extra_paths, song_name[:-4] + "-vorbis.raw")

    except Exception as e:
        print("###   SKIPPING SONG - FAILED TO QUERY METADATA   ###")
        print(f" download_track FAILED: [{track_id_str}][{extra_paths}][{prefix}][{prefix_value}][{disable_progressbar}]")
        print("SKIPPING SONG: ",e)
        print(f" download_track FAILED: [{artists}][{album_name}][{name}][{image_url}][{release_year}][{disc_number}][{track_number}][{scraped_song_id}][{is_playable}]")
        time.sleep(60)
        download_track(track_id_str, extra_paths,prefix=prefix, prefix_value=prefix_value, disable_progressbar=disable_progressbar)

    else:

        try:
            if not is_playable:
                print("###   SKIPPING:", song_name, "(SONG IS UNAVAILABLE)   ###")
            else:
                if os.path.isfile(filename) and os.path.getsize(filename) and SKIP_EXISTING_FILES:
                    print("###   SKIPPING: (SONG ALREADY EXISTS) :", song_name, "   ###")
                elif check_all_time and SKIP_PREVIOUSLY_DOWNLOADED:
                    print('###   SKIPPING: ' + song_name + ' (SONG ALREADY DOWNLOADED ONCE)   ###')
                else:
                    if track_id_str != scraped_song_id:
                        track_id_str = scraped_song_id

                    track_id = TrackId.from_base62(track_id_str)
                    # print("###   FOUND SONG:", song_name, "   ###")
                    realtime_started = time.time()
                    stream = SESSION.content_feeder().load(
                        track_id, VorbisOnlyAudioQuality(QUALITY), False, None)

                    os.makedirs(ROOT_PATH + extra_paths,exist_ok=True)

                    total_size = stream.input_stream.size
                    downloaded = 0
                    _CHUNK_SIZE = CHUNK_SIZE
                    fail = 0
                    bar_txt = song_name
                    if REALTIME_WAIT:
                        bitrate = 0
                        if QUALITY == AudioQuality.NORMAL:
                            bitrate = 96
                        elif QUALITY == AudioQuality.HIGH:
                            bitrate = 160
                        elif QUALITY == AudioQuality.VERY_HIGH:
                            bitrate = 320
                        #print("Bitrate is: " + str(bitrate * 125))
                        _CHUNK_SIZE = bitrate * 125
                        bar_txt = "\033[1;37;44m REALTIME \033[m " + bar_txt
                    with open(tempfile, 'wb') as file, tqdm(
                            desc=bar_txt,
                            total=total_size,
                            unit='B',
                            unit_scale=True,
                            unit_divisor=1024,
                            disable=disable_progressbar
                    ) as bar:
                        while downloaded <= total_size:
                            data = stream.input_stream.stream().read(_CHUNK_SIZE)

                            downloaded += len(data)
                            if REALTIME_WAIT:
                                realtime_wait(realtime_started, duration_ms, total_size, downloaded)                            
                            bar.update(file.write(data))                           
                            #print(f"[{total_size}][{_CHUNK_SIZE}] [{len(data)}] [{total_size - downloaded}] [{downloaded}]")
                            if (total_size - downloaded) < _CHUNK_SIZE:
                                _CHUNK_SIZE = total_size - downloaded
                            if len(data) == 0 : 
                                fail += 1                                
                            if fail > REINTENT_DOWNLOAD:
                                break

                    file.close()

                    convert_audio_format(tempfile, filename) # not actually converted if RAW_AUDIO_AS_IS                 
                    if not RAW_AUDIO_AS_IS:
                        META_GENRE = genre
                        if USE_MUTAGEN:
                            set_audio_tags_mutagen(filename, artists, name, album_name,
                                           release_year, disc_number, track_number, track_id_str, image_url)
                        else:
                            set_audio_tags(filename, artists, name, album_name,
                                           release_year, disc_number, track_number, track_id_str)
                            set_music_thumbnail(filename, image_url)
                        META_GENRE = False 
 
                    if not OVERRIDE_AUTO_WAIT and not REALTIME_WAIT:
                        time.sleep(ANTI_BAN_WAIT_TIME)

                    add_to_archive(scraped_song_id, os.path.basename(filename), artists[0], name)
        except Exception as e1:
            print("###   SKIPPING:", song_name, "(GENERAL DOWNLOAD ERROR)   ###", e1)
            if os.path.exists(filename):
                os.remove(filename)
            print(f" download_track GENERAL DOWNLOAD ERROR: [{track_id_str}][{extra_paths}][{prefix}][{prefix_value}][{disable_progressbar}]")
            download_track(track_id_str, extra_paths,prefix=prefix, prefix_value=prefix_value, disable_progressbar=disable_progressbar)


def download_album(album):
    """ Downloads songs from an album """
    global MULTI_CDS
    token = SESSION.tokens().get("user-read-email")
    artist, album_release_date, album_name, total_tracks = get_album_name(token, album)
    artist = sanitize_data(artist)
    album_name = sanitize_data(album_name)
    album_dir_str = f"{artist} - {album_release_date} - {album_name}"
    if ALBUM_DIR_SHORT:
        album_dir_str = f"{album_name}"
    tracks = get_album_tracks(token, album)
    print(f"\n  {artist} - ({album_release_date}) {album_name} [{total_tracks}]")
    disc_number_flag = False
    bar_txt = "Download Album"
    if REALTIME_WAIT:
        bar_txt = "\033[1;37;44m REALTIME \033[m " + bar_txt
    for track in tracks:
        if track['disc_number'] > 1:
            disc_number_flag = True            
    if disc_number_flag:
        MULTI_CDS = True
        if SPLIT_ALBUM_CDS:
            for n, track in tqdm(enumerate(tracks, start=1), unit_scale=True, unit='Song', total=len(tracks), desc=bar_txt):
                disc_number = str(track['disc_number']).zfill(2)
                download_track(track['id'], os.path.join(artist, album_dir_str, f"CD {disc_number}"),prefix=True, prefix_value=str(n), disable_progressbar=True)

        else:
            for n, track in tqdm(enumerate(tracks, start=1), unit_scale=True, unit='Song', total=len(tracks), desc=bar_txt):
                download_track(track['id'], os.path.join(artist, album_dir_str),prefix=True, prefix_value=str(n), disable_progressbar=True)

        MULTI_CDS = False            
    else: 
        for n, track in tqdm(enumerate(tracks, start=1), unit_scale=True, unit='Song', total=len(tracks), desc=bar_txt):
            download_track(track['id'], os.path.join(artist, album_dir_str),prefix=True, prefix_value=str(n), disable_progressbar=True)

def download_artist_albums(artist):
    """ Downloads albums of an artist """
    token = SESSION.tokens().get("user-read-email")
    albums = get_artist_albums(token, artist)
    total_albums = str(len(albums))
    print("Total Artist Albums to download: " + str(len(albums)) + "\n")

    for i in range(len(albums)):
        print("\n\nDownloading: " + str(i + 1) + "/" + total_albums)
        download_album(albums[i]['id'])
        antiban_wait()


def get_albums_artist(access_token, artists_id):
    """ returns list of albums in a artist """

    offset = 0
    limit = 50
    include_groups = 'album,compilation'

    headers = {'Authorization': f'Bearer {access_token}'}
    params = {'limit': limit, 'include_groups': include_groups, 'offset': offset}

    resp = requests.get(
        f'https://api.spotify.com/v1/artists/{artists_id}/albums', headers=headers, params=params).json()
    #print("###   Album Name:", resp['items'], "###")
    return resp['items']

def download_playlist(playlists, playlist_choice):
    """Downloads all the songs from a playlist"""
    token = SESSION.tokens().get("user-read-email")
    print("download_playlist:\nplaylists: " + playlists + "\n")

    playlist_songs = get_playlist_songs(
        token, playlists[int(playlist_choice) - 1]['id'])
    print(json.dumps(playlist_songs, indent=2))

    for song in playlist_songs:
        if PLAYLIST_SONG_ALBUMS:
            print("PLAYLIST_SONG_ALBUMS selected. Get entire albums based off of playlist.")
        else:
            if song['track']['id'] is not None:
                download_track(song['track']['id'], sanitize_data(
                    playlists[int(playlist_choice) - 1]['name'].strip()) + "/")
            print("\n")

def download_playlist_by_id(playlist_id, playlist_name):
    """Downloads all the songs from a playlist using playlist id"""
    token = SESSION.tokens().get("user-read-email")

    playlist_songs = get_playlist_songs(token, playlist_id)
    total_songs = len(playlist_songs)
    song_index = 1
    for song in playlist_songs:
        track_id = song['track']['id']
        song_name = song['track']['name']
        album_id = song['track']['album']['id']
        album_name = song['track']['album']['name']
        artist_name = song['track']['album']['artists'][0]['name']

        # Simple pre-check of downloaded. A long playlist resumed after failure
        # can cause too many api hits in rapid succession.
        check_all_time = track_id in get_previously_downloaded()
        if check_all_time and SKIP_PREVIOUSLY_DOWNLOADED:
            print("GET PLAYLIST SONGS * PRE-CHECK\n")
            print("###   SKIPPING: " + song_name + " (SONG ALREADY DOWNLOADED ONCE)   ###\n")

        elif PLAYLIST_SONG_ALBUMS: # Download all albums of playlist songs.
            if track_id is not None:
                print("PLAYLIST_SONG_ALBUMS selected. Get entire albums based off of the \"" + playlist_name + "\" playlist.\n")
                print(str(song_index) + "/" + str(total_songs) + " Downloading - Album: \"" + album_name + "\" by artist: " + artist_name + "\n")
                download_album(album_id)
            else:
                print(str(song_index) + "/" + str(total_songs) + " Downloading - Album: \"" + album_name + "\" by artist: " + artist_name + "\n")
                print(str(song_index) + "/" + str(total_songs) + song_name + " not available, skipping album\n")

        else: # Download songs only from playlist into folder with playlist name.
            if track_id is not None:
                print(str(song_index) + "/" + str(total_songs) + " Downloading \"" + song_name + "\" from the \"" + playlist_name + "\" playlist.\n")
                download_track(track_id, sanitize_data(playlist_name.strip()) + "/")
            else:
                print(str(song_index) + "/" + str(total_songs) + song_name + " not available, skipping\n")
        print("\n")

        song_index += 1

def download_from_user_playlist():
    """ Select which playlist(s) to download """
    token = SESSION.tokens().get("user-read-email")
    playlists = get_all_playlists(token)

    count = 1
    for playlist in playlists:
        print(str(count) + ": " + playlist['name'].strip())
        count += 1

    print("\n> SELECT A PLAYLIST BY ID")
    print("> SELECT A RANGE BY ADDING A DASH BETWEEN BOTH ID's")
    print("> For example, typing 10 to get one playlist or 10-20 to get\nevery playlist from 10-20 (inclusive)\n")

    playlist_choices = input("ID(s): ").split("-")

    if len(playlist_choices) == 1:
        download_playlist(playlists, playlist_choices[0])
    else:
        start = int(playlist_choices[0])
        end = int(playlist_choices[1]) + 1

        print(f"Downloading from {start} to {end}...")

        for playlist in range(start, end):
            download_playlist(playlists, playlist)

        print("\n**All playlists have been downloaded**\n")


# Core functions here

def check_raw():
    #global RAW_AUDIO_AS_IS, MUSIC_FORMAT
    global MUSIC_FORMAT
    if RAW_AUDIO_AS_IS:
        MUSIC_FORMAT = "ogg"


def main():
    """ Main function """
    check_raw()
    login()
    client()


if __name__ == "__main__":
    try:
        main()

    except KeyboardInterrupt:
        print('')
        sys.exit(0)
    except Exception as error:
        print(f"[!] ERROR {error} ")

