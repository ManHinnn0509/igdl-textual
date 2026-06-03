from __future__ import annotations

import threading, platform, subprocess, os

from typing import Optional

import requests

from pydantic import ValidationError

from instagrapi import Client
from instagrapi.types import Media
from instagrapi.exceptions import MediaNotFound

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal, VerticalScroll
from textual.widgets import Button, Input, Label, ProgressBar, Static, TextArea, Footer
from textual.screen import Screen
from textual.visual import VisualType

from rich.text import Text


# https://github.com/subzeroid/instagrapi/issues/2326
# https://gist.github.com/mrkeyiano/55bb0a6d29bcc1943d28b630450725d2
from instagrapi_patch import patch_instagrapi


'''
TODO:
- Add a window/screen for multiple inputs (With TextArea maybe?)
'''

# https://textual.textualize.io/widgets/progress_bar/#__tabbed_3_1

class BulkInputScreen(Screen):
    BINDINGS = [
        Binding("escape", "dismiss", show=False),
        Binding("ctrl+enter", "queue", "Queue & Close", show=True),
    ]

    DEFAULT_CSS = """
    BulkInputScreen {
        layout: vertical;
    }
    #bulk-title {
        padding: 1 1 0 1;
    }
    #bulk-ta {
        height: 1fr;
        width: 1fr;
        margin: 1;
    }
    #bulk-buttons {
        height: 3;
        padding: 0 1;
        content-align: right middle;
    }
    .btn {
        margin: 0 1 0 0;
    }
    """

    def compose(self):
        yield Static('Bulk input, 1 line 1 URL', id='bulk-title')
        self.ta = TextArea('', soft_wrap=True, id='bulk-ta', show_line_numbers=True)
        yield self.ta
        with Horizontal(id="bulk-buttons"):
            yield Button("Cancel", id="cancel", classes='btn')
            yield Button("Clear", id="clear", classes='btn')
            yield Button("Queue", id="queue", classes='btn')


    def on_mount(self):
        self.set_focus(self.ta)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel":
            self.app.pop_screen()
        elif event.button.id == "queue":
            self.action_queue()
            self.app.pop_screen()
        elif event.button.id == 'clear':
            self.ta.text = ''

    def action_dismiss(self):
        self.app.pop_screen()

    def action_queue(self):
        lines = [ln.strip() for ln in self.ta.text.splitlines()]
        urls = []
        for line in lines:
            if (line and line not in urls):
                urls.append(line)
        
        if (not urls):
            self.app.notify("No URL / code found.", severity="warning")
            return

        self.app: IGDL_App
        self.app.bulk_urls(urls)

class DownloadRow(Horizontal):
    DEFAULT_CSS = '''
    DownloadRow {
        width: 1fr;
        height: auto;
        padding: 1 1 0 1;
        /* ?? not sure how these works but whatever */
        align: center middle;
        content-align: center middle;
        /* test, debug color */
        /*background: #004400;*/
    }

    DownloadRow > #bar {
        width: auto;
        margin: 0 1 0 1;
    }
    DownloadRow > #filename,
    DownloadRow > #status {
        width: 0.3fr;
        text-overflow: ellipsis;
    }

    DownloadRow > #filename {
        text-align: left;
    }
    DownloadRow > #status{
        text-align: right;
    }
    '''
    def __init__(
            self,
            filename: str="FILENAME", status: str="STATUS",
            *children, name = None, id = None, classes = None, disabled = False, markup = True
        ):
        super().__init__(*children, name=name, id=id, classes=classes, disabled=disabled, markup=markup)
        self.filename = Static(filename, id='filename')
        self.progbar = ProgressBar(total=100, id='bar')
        self.status = Static(status, id='status')

    def compose(self):
        yield self.filename
        yield self.progbar
        yield self.status

    def update_status(self, new_status: VisualType):
        self.status.content = new_status
        self.status.refresh()
    
    def update_filename(self, new_filename: VisualType):
        self.filename.content = new_filename
        self.filename.refresh()

    def set_total(self, total: int):
        self.progbar.update(total=max(1, int(total)), progress=0)

    def set_progress(self, progress: int, total: Optional[int] = None):
        if (total is None):
            total = self.progbar.total or 100
        progress = max(0, int(progress))
        total = max(1, int(total))
        if (progress > total):
            total = progress
        self.progbar.update(progress=progress, total=total)

class IGDL_App(App):

    DOWNLOAD_DIR = './downloads'

    CSS = '''
    #hsplit { height: auto; }
    #vsplit { /*width: 80%;*/ }
    
    #input { width: 0.5fr; }
    .btn { margin: 0 1 0 0 ; }
    #output { height: 1fr; width: 1fr; }
    '''

    BINDINGS = [
        Binding("ctrl+q", "block_quit", show=False, priority=True),
        Binding("ctrl+z", "quit", "Quit", show=True, priority=True, key_display="^Z"),
        Binding("ctrl+f", "open_bulk", "Multi-URL", priority=True),
    ]

    theme = 'dracula'

    def action_open_bulk(self):
        self.push_screen(BulkInputScreen())

    def bulk_urls(self, urls: list[str]):
        for url in urls:
            row = self.create_row(url)
            self.output.mount(row)
            self._start_worker(url, row)

    def __init__(self, driver_class = None, css_path = None, watch_css = False, ansi_color = False):
        super().__init__(driver_class, css_path, watch_css, ansi_color)
        # instagram login
        self.client = Client()
        self._logged_in = False

        # create the widgets
        self.btn_opendir = Button('Open dir', id='open-dir', classes='btn')
        self.input = Input(id='input')
        self.btn_clear = Button('Clear', id='clear', classes='btn')
        self.btn_submit = Button('Submit', id='submit', classes='btn')
        self.output = VerticalScroll(id='output')

        # disable all their focuses
        self.btn_opendir.can_focus = False
        self.btn_clear.can_focus = False
        self.btn_submit.can_focus = False
        self.output.can_focus = False
    
    def login(self, session_filepath: str):
        if (self._logged_in):
            return
        try:
            self.client.load_settings(session_filepath)
            self._logged_in = True
            self.notify(f'Loaded {session_filepath}')
        except:
            self.notify('Unable to login with given session file', severity='error')

    def ui(self, fn, *args, **kwargs):
        self.call_from_thread(fn, *args, **kwargs)

    def compose(self):
        with Vertical(id='vsplit'):
            with Horizontal(id='hsplit'):
                yield self.btn_opendir
                yield self.input
                yield self.btn_clear
                yield self.btn_submit
            yield self.output

    def on_button_pressed(self, event: Button.Pressed):
        btn_id = event.button.id
        if (btn_id == 'clear'):
            self.input.value = ''

        elif (btn_id == 'submit'):
            url = self.input.value
            if (not url):
                return
            self.input.value = ''
            row = self.create_row(url)
            self.output.mount(row)
            self._start_worker(url, row)

        elif (btn_id == 'open-dir'):
            os_name = platform.system()
            if (os_name == 'Windows'):
                exc = 'explorer'
            elif (os_name == 'Linux'):
                exc = 'xdg-open'
            elif (os_name == 'Darwin'):
                exc = 'open'
            else:
                return

            dir_path = os.path.abspath(self.DOWNLOAD_DIR)
            cmd = [exc, dir_path]
            #self.notify(str(cmd))
            subprocess.run(cmd)

    
    def create_row(self, url: str):
        id = url.split('?')[0]
        if (id.endswith('/')):
            id = id[:-1]
        id = id.split("/")[-1]
        return DownloadRow(filename=id)

    def _start_worker(self, ig_url: str, row: DownloadRow):
        threading.Thread(
            target=self._worker,
            args=(ig_url, row),
            daemon=True
        ).start()

    def _worker(self, ig_url: str, row: DownloadRow):
        try:

            row.update_status(f'Getting medias pk...')
            pk = get_pk(self.client, ig_url)

            row.update_status(f'Fetching medias info...')
            info = self.client.media_info(pk)

            row.update_status(f'Getting download url(s)...')
            urls = get_download_url(info)
            urls = [urls] if (isinstance(urls, str)) else urls

            row.update_status(f'Found total {len(urls)} urls')

            for idx, url in enumerate(urls):
                filename = extract_filename(url)
                path = f'{self.DOWNLOAD_DIR}/{filename}'

                if idx == 0:
                    self.ui(row.update_filename, filename)
                    self.ui(row.update_status, f'Downloading {idx + 1} / {len(urls)} ...')
                    threading.Thread(target=self._download_one, args=(url, path, row), daemon=True).start()
                else:
                    r = DownloadRow(filename=filename, status=f'Downloading {idx + 1} / {len(urls)} ...')
                    self.ui(self.output.mount, r)
                    threading.Thread(target=self._download_one, args=(url, path, r), daemon=True).start()

        except ValidationError as e:
            row.update_status(Text('Error when validating Media', style='red'))

        except MediaNotFound as e:
            row.update_status(Text('Media not found or removed', style='red'))

        except ValueError as e:
            row.update_status(Text('Invalid code/url', style='red'))

        except Exception as e:
            self.ui(row.update_status, Text(f'Init error: {e}', style='red'))

    def _download_one(self, url: str, path: str, row: DownloadRow):
        """Minimal implementation: requests + streaming; includes initialization progress."""
        INIT_WEIGHT = 128 * 1024  # Treat init as 128KB of progress

        try:
            # 1) Initialization phase
            self.ui(row.update_status, 'Initiating connection...')
            total = INIT_WEIGHT
            content_len = 0
            try:
                h = requests.head(url, timeout=10)
                if h.ok and h.headers.get('Content-Length'):
                    content_len = int(h.headers['Content-Length'])
            except Exception:
                pass

            # If Content-Length is missing, estimate 1MB first; it will expand dynamically during download
            if content_len <= 0:
                content_len = 1024 * 1024

            total += content_len
            self.ui(row.set_total, total)

            # Consume the initialization weight first
            done = INIT_WEIGHT
            self.ui(row.set_progress, done, total)
            self.ui(row.update_status, 'Downloading...')

            # 2) Actual download
            with requests.get(url, stream=True, timeout=20) as r:
                r.raise_for_status()
                real_len = int(r.headers.get('Content-Length', '0') or 0)
                if real_len > 0 and INIT_WEIGHT + real_len != total:
                    total = INIT_WEIGHT + real_len
                    self.ui(row.set_progress, done, total)

                with open(path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)

                        # If the total is underestimated, expand it while downloading to avoid reaching 100% too early
                        if done > total:
                            total = done
                            self.ui(row.set_progress, done, total)
                        else:
                            self.ui(row.set_progress, done, None)

            self.ui(row.update_status, Text('Done!', style='bold'))
            self.ui(row.set_progress, total, total)

        except Exception as e:
            self.ui(row.update_status, Text(f'Error: {e}', style='red'))
            filename = extract_filename(url)
            os.remove(f'{self.DOWNLOAD_DIR}/{filename}')

def extract_filename(url: str):
    return url.split('?')[0].split('/')[-1]

def get_pk(cl: Client, s: str):
    if (s.startswith("http")):
        return cl.media_pk_from_url(s)
    else:
        return cl.media_pk_from_code(s)

def get_download_url(info: Media):
    '''
        Photo - When media_type=1 \n
        Video - When media_type=2 and product_type=feed \n
        IGTV  - When media_type=2 and product_type=igtv \n
        Reel  - When media_type=2 and product_type=clips \n
        Album - When media_type=8 \n
    '''
    if (info.media_type == 1):
        return str(info.thumbnail_url)

    # Couldn't find any test case, so all of them would return `info.video_url` for now
    elif (info.media_type == 2):
        if (info.product_type == 'feed'):
            return str(info.video_url)
        
        elif (info.product_type == 'igtv'):
            return str(info.video_url)
        
        elif (info.product_type == 'clips'):
            return str(info.video_url)
        
        else:
            return None
    
    elif (info.media_type == 8):
        urls = []
        for resource in info.resources:
            url = resource.video_url if (resource.video_url != None) else resource.thumbnail_url
            urls.append(str(url))

        return urls
    
    else:
        return None

if (__name__ == '__main__'):
    patch_instagrapi()
    app = IGDL_App()
    os.makedirs(app.DOWNLOAD_DIR, exist_ok=True)
    app.login('./settings.json')
    app.run()
