import os, requests
from getpass import getpass
from appdirs import user_config_dir
#from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
from librespot.core import Session
from librespot.audio.decoders import AudioQuality, VorbisOnlyAudioQuality
#from librespot.metadata import TrackId, EpisodeId





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
#SESSION: Session = None


def login():
    """ Authenticates with Spotify and saves credentials to a file """
   # global SESSION
    

    if os.path.isfile(CREDENTIALS):
        try:
            #conf = Session.Configuration.Builder().set_stored_credential_file(CREDENTIALS).set_store_credentials(False).build()
            #SESSION = Session.Builder(conf).stored_file().create()
            #print("Session from creds")
            #return Session.Builder(conf).stored_file().create()
            Zcfg.session_from_file()
            print("Logged in from credentials.")
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
            #os.makedirs(CONFIG_DIR, exist_ok=True)
            #conf = Session.Configuration.Builder().set_stored_credential_file(CREDENTIALS).build()
            #SESSION = Session.Builder(conf).user_pass(user_name, password).create()
            #return Session.Builder(conf).user_pass(user_name, password).create()
            Zcfg.session_from_creds(user_name, password)
            print("Logged in with name password.")
            return
        except BaseException as e:
            print(f"Login error, Username or Pass incorrect?\n[!] ERROR {e} \n")


class Zcfg:
    '''Get and set globals'''
    #pass
    SESSION: Session = None

    @classmethod
    def get_root_path(cls) -> str:
        '''Return Music dir'''
        return os.path.expanduser("~/Music/ZSpotify Music/")

    @classmethod
    def get_raw_audio_as_is(cls) -> bool:
        '''Leave audio stream alone'''
        return RAW_AUDIO_AS_IS

    @classmethod
    def get_skip_existing_files(cls) -> bool:
        '''Skip if file exists'''
        return SKIP_EXISTING_FILES

    @classmethod
    def get_skip_previously_downloaded(cls) -> bool:
        '''Skip if downloaded before'''
        return SKIP_PREVIOUSLY_DOWNLOADED

    @classmethod
    def get_album_dir_short(cls) -> bool:
        '''Album name in dir only'''
        return ALBUM_DIR_SHORT

    @classmethod
    def get_album_in_file_name(cls) -> bool:
        '''Album name in file name'''
        return ALBUM_IN_FILENAME

    @classmethod
    def get_force_premium(cls) -> bool:
        '''Returns FORCE_PREMIUM'''
        return FORCE_PREMIUM

    @classmethod
    def get_use_vbr(cls) -> bool:
        '''Use variable bitrate'''
        return USE_VBR

    @classmethod
    def get_override_auto_wait(cls) -> bool:
        '''Return OVERRIDE_AUTO_WAIT'''
        return OVERRIDE_AUTO_WAIT

    @classmethod
    def get_root_podcast_path(cls) -> str:
        '''Return Podcast dir'''
        return ROOT_PODCAST_PATH

    @classmethod
    def get_music_format(cls) -> str:
        '''Return MUSIC_FORMAT'''
        return MUSIC_FORMAT

    @classmethod
    def get_anti_ban_wait_time_albums(cls) -> int:
        '''Wait time in seconds'''
        return ANTI_BAN_WAIT_TIME_ALBUMS

    @classmethod
    def get_anti_ban_wait_time(cls) -> int:
        '''Wait time in seconds'''
        return ANTI_BAN_WAIT_TIME

    @classmethod
    def get_chunk_size(cls) -> int:
        '''Return Chunk size'''
        return CHUNK_SIZE

    @classmethod
    def get_limit(cls) -> int:
        '''Retrieval limit'''
        return LIMIT

    @classmethod
    def get_reintent_download(cls) -> int:
        '''Returns REINTENT_DOWNLOAD int'''
        return REINTENT_DOWNLOAD

    @classmethod
    def session_from_file(cls):
        conf = Session.Configuration.Builder().set_stored_credential_file(CREDENTIALS).set_store_credentials(False).build()
        #SESSION = Session.Builder(conf).stored_file().create()
        print("Session from creds")
        session = Session.Builder(conf).stored_file().create()
        #cls.SESSION = Session.Builder().stored_file().create()

        if session.is_valid():
            cls.SESSION = session
            return
        else:
            print(f"Invalid credentials in {CREDENTIALS}")

    @classmethod
    def session_from_creds(cls, user_name, password):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        conf = Session.Configuration.Builder().set_stored_credential_file(CREDENTIALS).build()
        #SESSION = Session.Builder(conf).user_pass(user_name, password).create()
        session = Session.Builder(conf).user_pass(user_name, password).create()

        if session.is_valid():
            cls.SESSION = session
            return
        else:
            print("Login with name and password failed.")

    @classmethod
    def get_token(cls):
        return cls.SESSION.tokens().get_token('user-read-email', 'playlist-read-private', 'user-library-read').access_token

    @classmethod
    def get_stream(cls, track_id, quality):
        return cls.SESSION.content_feeder().load(
            track_id, VorbisOnlyAudioQuality(quality), False, None)

    @classmethod
    def check_premium(cls):
        return bool((cls.SESSION.get_user_attribute("type") == "premium") or cls.get_force_premium())
