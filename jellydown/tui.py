"""Textual UI for JellyfinDownloader.

Stage 3 scope: read-only library tree on the left, live downloads table on
the right. No actions are wired in yet (Enter on a leaf is a no-op); see
stage 4 for download enqueue, cancel, and remove keys.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Select,
    Tree,
)
from textual.worker import Worker, WorkerState

from .api import jget, list_library_items
from .config import save_config
from .download import fetch_audio_tracks, fetch_subtitle_tracks
from .download_manager import (
    CANCELLED,
    DONE,
    DownloadManager,
    EV_ADDED,
    EV_PROGRESS,
    EV_REMOVED,
    EV_STATE,
    FAILED,
)
from .ui import filename_for
from .utils import format_episode_label, normalize_lang, safe_int

log = logging.getLogger(__name__)


def _human_speed(speed: float) -> str:
    if speed <= 0:
        return "-"
    if speed >= 1e6:
        return f"{speed / 1e6:.1f} MB/s"
    if speed >= 1e3:
        return f"{speed / 1e3:.1f} KB/s"
    return f"{speed:.0f} B/s"


def _human_progress(downloaded: int, total: int) -> str:
    if not total:
        if not downloaded:
            return "-"
        return f"{downloaded / 1e6:.1f} MB"
    pct = downloaded / total * 100
    return f"{pct:.1f}%"


class _AppLogHandler(logging.Handler):
    """Routes jellydown logger records to the TUI's notification system."""

    def __init__(self, app: "JellydownApp"):
        super().__init__()
        self._app = app

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            return
        if record.levelno >= logging.ERROR:
            severity = "error"
        elif record.levelno >= logging.WARNING:
            severity = "warning"
        else:
            severity = "information"
        try:
            # notify is thread-safe via call_from_thread under the hood, but
            # we play it safe.
            if threading.current_thread() is threading.main_thread():
                self._app.notify(msg, severity=severity)
            else:
                self._app.call_from_thread(self._app.notify, msg, severity=severity)
        except Exception:
            pass


class ButtonRow(Horizontal):
    """Right-aligned horizontal row of buttons. Pinned to 3 rows so it doesn't
    expand and consume the dialog's leftover space.

    CSS-via-DEFAULT_CSS for height didn't survive Horizontal's inherited
    `height: 1fr` in our environment (textual 8.2.5), so we set it
    imperatively on mount.
    """

    def on_mount(self) -> None:
        self.styles.height = 3
        self.styles.align_horizontal = "right"
        self.styles.margin = (1, 0, 0, 0)
        for btn in self.query("Button"):
            btn.styles.margin = (0, 0, 0, 1)
            btn.styles.min_width = 12


class DownloadPromptScreen(ModalScreen):
    """Asks for output dir, audio language, and subtitle choice.

    Audio + subtitle Selects are populated with the language codes actually
    present on the selected items. The scan runs in a worker thread; the
    modal is usable immediately with cfg defaults and the Selects update
    when the scan completes.

    Result dict keys:
      out_dir (str)
      audio_lang (str)            — language code e.g. 'eng'
      sub_choice ('none' | 'all' | <language code>)

    Priority shortcuts:
      d  start download   c  cancel   a  focus audio   s  focus subtitle
    """

    BINDINGS = [
        Binding("d", "submit", "Download", priority=True),
        Binding("c", "cancel", "Cancel", priority=True),
        Binding("a", "focus_audio", "Audio", priority=True),
        Binding("s", "focus_subs", "Subtitles", priority=True),
        Binding("escape", "cancel", "Cancel", priority=True),
        # Form-style navigation. Priority so the Select widget can't consume
        # arrows for its own (closed-state) handling. When a dropdown is
        # actually open, `_cycle_focus` defers to the Select.
        Binding("up", "focus_previous", "Prev field", priority=True),
        Binding("down", "focus_next", "Next field", priority=True),
    ]

    DEFAULT_CSS = """
    DownloadPromptScreen {
        align: center middle;
    }
    #dialog {
        width: 70;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #dialog Label {
        height: 1;
        width: 1fr;
    }
    #dialog Label.title {
        text-style: bold;
        margin-bottom: 1;
    }
    #dialog Label.field {
        margin-top: 1;
    }
    #dialog Input,
    #dialog Select {
        height: 3;
        width: 1fr;
    }
    /* Cap the dropdown overlay so it doesn't dominate the layout when open. */
    #dialog Select > SelectOverlay {
        max-height: 10;
    }
    """

    def __init__(self, summary: str, default_out: str,
                 default_audio: str, default_sub_lang: str,
                 items: list[dict], base: str, api_key: str, user_id: str):
        super().__init__()
        self._summary = summary
        self._default_out = default_out
        self._default_audio = default_audio or "eng"
        self._default_sub_lang = default_sub_lang or "eng"
        self._items = items
        self._base = base
        self._api_key = api_key
        self._user_id = user_id

    def _initial_audio_options(self) -> list[tuple[str, str]]:
        return [(self._default_audio, self._default_audio)]

    def _initial_sub_options(self) -> list[tuple[str, str]]:
        opts: list[tuple[str, str]] = [("None", "none"), ("All", "all")]
        if self._default_sub_lang and self._default_sub_lang not in ("none", "all"):
            opts.append((self._default_sub_lang, self._default_sub_lang))
        return opts

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._summary, classes="title")
            yield Label("Output directory:", classes="field")
            yield Input(value=self._default_out, id="outdir")
            yield Label("Audio language:  (a)", classes="field")
            yield Select(
                self._initial_audio_options(),
                id="audio_lang",
                value=self._default_audio,
                allow_blank=False,
            )
            yield Label("Subtitles:  (s)", classes="field")
            yield Select(
                self._initial_sub_options(),
                id="sub_choice",
                value="none",
                allow_blank=False,
            )
            with ButtonRow(id="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Download", id="ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#ok", Button).focus()
        self.run_worker(
            self._scan_languages, thread=True, exclusive=True,
            name="lang-scan", description="Scanning language tracks",
        )

    def _scan_languages(self) -> dict:
        """Worker: fetch audio + subtitle tracks across all items.

        Returns a dict {audio: set, sub: set} of normalized language codes.
        """
        audio_codes: set[str] = set()
        sub_codes: set[str] = set()
        for item in self._items:
            item_id = item.get("Id")
            if not item_id:
                continue
            try:
                tracks = fetch_audio_tracks(self._base, self._api_key, item_id)
                for t in tracks:
                    code = normalize_lang(t.get("language") or "")
                    if code and code != "und":
                        audio_codes.add(code)
            except Exception:
                log.exception("audio scan failed for %s", item_id)
            try:
                subs = fetch_subtitle_tracks(
                    self._base, self._api_key, self._user_id, item_id,
                )
                for t in subs:
                    code = normalize_lang(t.get("lang") or "")
                    if code and code != "und":
                        sub_codes.add(code)
            except Exception:
                log.exception("subtitle scan failed for %s", item_id)
        return {"audio": audio_codes, "sub": sub_codes}

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.name != "lang-scan" or worker.state != WorkerState.SUCCESS:
            return
        result = worker.result or {}
        self._populate_selects(result.get("audio") or set(),
                               result.get("sub") or set())

    def _populate_selects(self, audio_codes: set[str], sub_codes: set[str]) -> None:
        # Audio: union of scan results + cfg default. Preserve current
        # selection if still valid.
        audio_select = self.query_one("#audio_lang", Select)
        try:
            current_audio = str(audio_select.value)
        except Exception:
            current_audio = self._default_audio
        audio_pool = set(audio_codes)
        audio_pool.add(self._default_audio)
        audio_pool.add(current_audio)
        audio_pool.discard("")
        audio_opts = [(c, c) for c in sorted(audio_pool)]
        audio_select.set_options(audio_opts)
        try:
            audio_select.value = current_audio if current_audio in audio_pool \
                else self._default_audio
        except Exception:
            log.exception("Failed to set audio select value")

        # Subtitle: None / All on top, then any detected language codes,
        # plus the cfg default if not already in the list.
        sub_select = self.query_one("#sub_choice", Select)
        try:
            current_sub = str(sub_select.value)
        except Exception:
            current_sub = "none"
        sub_pool = set(sub_codes)
        if self._default_sub_lang and self._default_sub_lang not in ("none", "all"):
            sub_pool.add(self._default_sub_lang)
        sub_opts = [("None", "none"), ("All", "all")]
        for c in sorted(sub_pool):
            sub_opts.append((c, c))
        sub_select.set_options(sub_opts)
        valid_values = {v for _, v in sub_opts}
        try:
            sub_select.value = current_sub if current_sub in valid_values else "none"
        except Exception:
            log.exception("Failed to set subtitle select value")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(None)
            return
        self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def action_submit(self) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_focus_audio(self) -> None:
        self.query_one("#audio_lang", Select).focus()

    def action_focus_subs(self) -> None:
        self.query_one("#sub_choice", Select).focus()

    # Top-level form fields, in tab order. action_focus_next/previous cycle
    # through these explicitly so we don't descend into Select's internal
    # child widgets (which have no ids and confuse the user).
    _FIELD_IDS = ("outdir", "audio_lang", "sub_choice", "cancel", "ok")

    def _cycle_focus(self, forward: bool) -> None:
        widgets = [self.query_one(f"#{fid}") for fid in self._FIELD_IDS]
        current = self.focused
        idx = -1
        for i, w in enumerate(widgets):
            if current is w or (current is not None and current in w.walk_children()):
                idx = i
                break
        next_idx = (idx + (1 if forward else -1)) % len(widgets)
        widgets[next_idx].focus()

    def check_action(self, action: str, parameters):
        # Disable arrow-cycling while a Select dropdown is open so the
        # Select widget can handle option navigation itself.
        if action in ("focus_previous", "focus_next"):
            for sel_id in ("audio_lang", "sub_choice"):
                try:
                    sel = self.query_one(f"#{sel_id}", Select)
                except Exception:
                    continue
                if sel.expanded:
                    return False
        return True

    def action_focus_previous(self) -> None:
        self._cycle_focus(forward=False)

    def action_focus_next(self) -> None:
        self._cycle_focus(forward=True)

    def _submit(self) -> None:
        outdir = self.query_one("#outdir", Input).value.strip() or "."
        audio_select = self.query_one("#audio_lang", Select)
        sub_select = self.query_one("#sub_choice", Select)
        audio = str(audio_select.value) if audio_select.value not in (None, Select.BLANK) \
            else self._default_audio
        sub = str(sub_select.value) if sub_select.value not in (None, Select.BLANK) \
            else "none"
        self.dismiss({
            "out_dir": outdir,
            "audio_lang": audio,
            "sub_choice": sub,
        })


# (key, label, type) for each editable field. Type is "int" or "str".
SETTINGS_FIELDS: list[tuple[str, str, str]] = [
    ("VideoCodec", "Video codec", "str"),
    ("AudioCodec", "Audio codec", "str"),
    ("VideoBitrate", "Video bitrate (bits/sec, 0=original)", "int"),
    ("AudioBitrate", "Audio bitrate (bits/sec)", "int"),
    ("MaxAudioChannels", "Max audio channels", "int"),
    ("PreferredAudioLanguage", "Preferred audio language", "str"),
    ("PreferredSubtitleLanguage", "Preferred subtitle language", "str"),
    ("ParallelDownloads", "Parallel downloads (1-16)", "int"),
]


def _settings_leaf_label(label: str, value) -> str:
    return f"{label}: {value}"


class EditBar(Input):
    """Input docked at the bottom of the screen for in-tree settings edits.

    Esc dismisses the edit without saving; Enter (Input.Submitted) saves —
    handled at the App level since saving needs config + leaf-refresh access.
    """

    BINDINGS = [
        Binding("escape", "cancel_edit", "Cancel", priority=True),
    ]

    def action_cancel_edit(self) -> None:
        self.app.cancel_setting_edit()


class LibraryTree(Tree):
    """Tree with mc-style left/right semantics.

    Right: expand current node, else descend to first child.
    Left:  collapse current node, else ascend to parent.
    """

    BINDINGS = [
        Binding("right", "expand_or_descend", "Expand", priority=True),
        Binding("left", "collapse_or_ascend", "Collapse", priority=True),
    ]

    def action_expand_or_descend(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and not node.is_expanded:
            node.expand()
            return
        children = list(node.children)
        if children:
            self.move_cursor(children[0])

    def action_collapse_or_ascend(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded:
            node.collapse()
            return
        if node.parent is not None:
            self.move_cursor(node.parent)


class HelpScreen(ModalScreen):
    """Read-only keybindings reference. Dismisses with None on any key/click."""

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-dialog {
        width: 70;
        height: auto;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }
    #help-dialog Label.title {
        text-style: bold;
        margin-bottom: 1;
    }
    #help-buttons {
        height: auto;
        align-horizontal: right;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape,enter,q", "close", "Close", priority=True),
    ]

    HELP_TEXT = (
        "Library tree (left)\n"
        "  ↑ ↓       navigate\n"
        "  ← →       collapse / expand (or descend / ascend)\n"
        "  PageUp/Dn jump page\n"
        "  Enter     download focused item (or marked items),\n"
        "            or edit a setting under Settings\n"
        "  Space     toggle mark on focused item\n"
        "  d         download marked items, or focused if none marked\n"
        "\n"
        "Downloads (right)\n"
        "  ↑ ↓       focus row\n"
        "  c         cancel focused download\n"
        "  r         remove finished/cancelled row\n"
        "\n"
        "Download dialog\n"
        "  ↑ ↓       move between fields\n"
        "  Enter     activate field (open dropdown / submit form)\n"
        "  d         start download    c   cancel\n"
        "  a         focus audio       s   focus subtitle\n"
        "  Esc       cancel\n"
        "\n"
        "Settings edit\n"
        "  Enter     save the value\n"
        "  Esc       cancel without saving\n"
        "\n"
        "Global\n"
        "  s         jump to Settings branch\n"
        "  ?         this help\n"
        "  q         quit\n"
    )

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("Keybindings", classes="title")
            yield Label(self.HELP_TEXT)
            with Horizontal(id="help-buttons"):
                yield Button("Close", id="help-close", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "help-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


class JellydownApp(App):
    """Textual app: library tree (left) + downloads (right)."""

    CSS = """
    Screen {
        layout: vertical;
    }

    Horizontal {
        height: 1fr;
    }

    #library {
        width: 60%;
        border: solid $accent;
    }

    #downloads {
        width: 40%;
        border: solid $accent;
    }

    #edit-bar {
        dock: bottom;
        height: 3;
        border: solid $accent;
    }

    #edit-bar.hidden {
        display: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        # priority=True so Space wins over Tree's expand/collapse binding
        Binding("space", "toggle_mark", "Mark", priority=True),
        Binding("d", "download_marked", "Download marked"),
        Binding("c", "cancel_job", "Cancel"),
        Binding("r", "remove_job", "Remove"),
        # Non-priority so a modal's 's' / '?' bindings can win when on top.
        Binding("s", "settings", "Settings"),
        Binding("question_mark", "help", "Help"),
    ]

    def __init__(self, base: str, api_key: str, user_id: str, cfg: dict):
        super().__init__()
        self.base = base
        self.api_key = api_key
        self.user_id = user_id
        self.cfg = cfg
        self.manager = DownloadManager(base, api_key, user_id, cfg)
        # Map job.id → (row_key in the DataTable). Populated on EV_ADDED.
        self._row_keys: dict[str, Any] = {}
        # Tree node id → original label (for redrawing the mark prefix).
        self._marked: dict[int, str] = {}
        # Active settings edit: dict with key, kind, label, leaf_node, or None.
        self._editing: dict | None = None

    # ---------- Composition ----------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal():
            tree: Tree = LibraryTree("Library", id="library")
            tree.guide_depth = 3
            yield tree
            yield DataTable(id="downloads", zebra_stripes=True)
        yield EditBar("", id="edit-bar", classes="hidden")
        yield Footer()

    def on_mount(self) -> None:
        self.title = "JellyfinDownloader"
        self.sub_title = self.base
        self._install_log_handler()

        tree = self.query_one("#library", Tree)
        tree.root.expand()
        tree.root.data = {"kind": "root"}
        series_node = tree.root.add("Series", data={"kind": "series_root"})
        movies_node = tree.root.add("Movies", data={"kind": "movies_root"})
        tree.root.add("Settings", data={"kind": "settings_root"})
        # Show a placeholder child so the user sees expandability and lazy
        # loading replaces it on first expand.
        series_node.add_leaf("(loading on expand…)", data={"kind": "placeholder"})
        movies_node.add_leaf("(loading on expand…)", data={"kind": "placeholder"})

        table = self.query_one("#downloads", DataTable)
        table.cursor_type = "row"
        table.add_columns("File", "Status", "Progress", "Speed")

        bar = self.query_one("#edit-bar", EditBar)
        bar.can_focus = False  # only focusable while shown

        self.manager.subscribe(self._on_manager_event)
        # Tree owns initial focus.
        tree.focus()

    # ---------- Lazy tree loading ----------

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node = event.node
        data = node.data or {}
        kind = data.get("kind")
        # Only fetch if we still have the placeholder child.
        if not self._needs_loading(node):
            return

        if kind == "series_root":
            self._load_series_root(node)
        elif kind == "movies_root":
            self._load_movies_root(node)
        elif kind == "series":
            self._load_seasons(node)
        elif kind == "season":
            self._load_episodes(node)
        elif kind == "settings_root":
            self._populate_settings(node)

    @staticmethod
    def _needs_loading(node) -> bool:
        children = list(node.children)
        if not children:
            return True
        return any((c.data or {}).get("kind") == "placeholder" for c in children)

    @staticmethod
    def _clear_placeholder(node) -> None:
        for child in list(node.children):
            if (child.data or {}).get("kind") == "placeholder":
                child.remove()

    def _load_series_root(self, node) -> None:
        self.run_worker(
            lambda: list_library_items(self.base, self.api_key, self.user_id, "Series"),
            name=f"load-series-root-{id(node)}",
            group="tree",
            thread=True,
            description="Loading series",
        )
        self._pending_loads = getattr(self, "_pending_loads", {})
        self._pending_loads[f"load-series-root-{id(node)}"] = ("series_root", node)

    def _load_movies_root(self, node) -> None:
        name = f"load-movies-root-{id(node)}"
        self.run_worker(
            lambda: list_library_items(self.base, self.api_key, self.user_id, "Movie"),
            name=name,
            group="tree",
            thread=True,
            description="Loading movies",
        )
        self._pending_loads = getattr(self, "_pending_loads", {})
        self._pending_loads[name] = ("movies_root", node)

    def _load_seasons(self, node) -> None:
        item = (node.data or {}).get("item") or {}
        series_id = item.get("Id")
        if not series_id:
            return
        name = f"load-seasons-{series_id}"

        def fetch():
            data = jget(
                self.base, f"/Shows/{series_id}/Seasons", self.api_key,
                params={"UserId": self.user_id},
            )
            return data.get("Items", data)

        self.run_worker(fetch, name=name, group="tree", thread=True,
                        description=f"Loading seasons of {item.get('Name', '')}")
        self._pending_loads = getattr(self, "_pending_loads", {})
        self._pending_loads[name] = ("seasons", node)

    def _load_episodes(self, node) -> None:
        data = node.data or {}
        season = data.get("item") or {}
        series_id = data.get("series_id")
        season_id = season.get("Id")
        if not series_id or not season_id:
            return
        name = f"load-episodes-{season_id}"

        def fetch():
            r = jget(
                self.base, f"/Shows/{series_id}/Episodes", self.api_key,
                params={
                    "UserId": self.user_id,
                    "SeasonId": season_id,
                    "Fields": "MediaSources,Overview,RunTimeTicks,SeriesName,"
                              "ParentIndexNumber,IndexNumber,Name",
                    "SortBy": "IndexNumber",
                    "SortOrder": "Ascending",
                },
            )
            return r.get("Items", [])

        self.run_worker(fetch, name=name, group="tree", thread=True,
                        description=f"Loading episodes of {season.get('Name', '')}")
        self._pending_loads = getattr(self, "_pending_loads", {})
        self._pending_loads[name] = ("episodes", node)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        worker = event.worker
        if worker.state != WorkerState.SUCCESS:
            if worker.state == WorkerState.ERROR:
                log.error("Worker %s failed: %s", worker.name, worker.error)
                self.notify(f"Failed to load: {worker.error}", severity="error")
            return
        pending = getattr(self, "_pending_loads", {}) or {}
        info = pending.pop(worker.name, None)
        if info is None:
            return
        kind, node = info
        result = worker.result
        if kind == "series_root":
            self._populate_series(node, result)
        elif kind == "movies_root":
            self._populate_movies(node, result)
        elif kind == "seasons":
            self._populate_seasons(node, result)
        elif kind == "episodes":
            self._populate_episodes(node, result)

    def _populate_series(self, node, items: list[dict]) -> None:
        self._clear_placeholder(node)
        if not items:
            node.add_leaf("(no series)", data={"kind": "empty"})
            return
        for s in items:
            label = s.get("Name") or "(no name)"
            new_node = node.add(label, data={"kind": "series", "item": s})
            new_node.add_leaf("(loading on expand…)", data={"kind": "placeholder"})

    def _populate_movies(self, node, items: list[dict]) -> None:
        self._clear_placeholder(node)
        if not items:
            node.add_leaf("(no movies)", data={"kind": "empty"})
            return
        for m in items:
            label = m.get("Name") or "(no name)"
            node.add_leaf(label, data={"kind": "movie", "item": m})

    def _populate_seasons(self, node, items: list[dict]) -> None:
        self._clear_placeholder(node)
        series = (node.data or {}).get("item") or {}
        series_id = series.get("Id")
        if not items:
            node.add_leaf("(no seasons)", data={"kind": "empty"})
            return
        for s in items:
            snum = safe_int(s.get("IndexNumber"))
            label = s.get("Name") or (f"Season {snum}" if snum is not None else "Season")
            new_node = node.add(
                label,
                data={"kind": "season", "item": s, "series_id": series_id},
            )
            new_node.add_leaf("(loading on expand…)", data={"kind": "placeholder"})

    def _populate_episodes(self, node, items: list[dict]) -> None:
        self._clear_placeholder(node)
        if not items:
            node.add_leaf("(no episodes)", data={"kind": "empty"})
            return
        for ep in items:
            node.add_leaf(format_episode_label(ep), data={"kind": "episode", "item": ep})

    def _populate_settings(self, node) -> None:
        # Settings has no async load; just enumerate fields once.
        for key, label, kind in SETTINGS_FIELDS:
            value = self.cfg.get(key, "")
            node.add_leaf(
                _settings_leaf_label(label, value),
                data={"kind": "setting", "key": key, "label": label, "type": kind},
            )

    def _refresh_setting_leaf(self, leaf) -> None:
        data = leaf.data or {}
        leaf.set_label(_settings_leaf_label(data["label"], self.cfg.get(data["key"], "")))

    # ---------- Download manager subscription ----------

    def _on_manager_event(self, ev: str, job) -> None:
        # Subscribers fire from worker threads in production; tests may call
        # this on the main thread. Marshal only when we're off the UI thread.
        if threading.current_thread() is threading.main_thread():
            self._handle_manager_event(ev, job)
        else:
            self.call_from_thread(self._handle_manager_event, ev, job)

    def _handle_manager_event(self, ev: str, job) -> None:
        table = self.query_one("#downloads", DataTable)
        if ev == EV_ADDED:
            row_key = table.add_row(
                job.filename, job.status, "-", "-",
                key=job.id,
            )
            self._row_keys[job.id] = row_key
        elif ev == EV_PROGRESS:
            row_key = self._row_keys.get(job.id)
            if row_key is None:
                return
            cols = table.ordered_columns
            table.update_cell(row_key, cols[2].key, _human_progress(job.downloaded, job.total))
            table.update_cell(row_key, cols[3].key, _human_speed(job.speed))
        elif ev == EV_STATE:
            row_key = self._row_keys.get(job.id)
            if row_key is None:
                return
            cols = table.ordered_columns
            table.update_cell(row_key, cols[1].key, job.status)
        elif ev == EV_REMOVED:
            row_key = self._row_keys.pop(job.id, None)
            if row_key is not None:
                table.remove_row(row_key)

    # ---------- Actions: download / cancel / remove ----------

    @staticmethod
    def _is_downloadable(node) -> bool:
        return ((node.data or {}).get("kind") in ("movie", "episode"))

    def on_tree_node_selected(self, event) -> None:
        node = event.node
        kind = (node.data or {}).get("kind")
        if kind == "setting":
            self._begin_setting_edit(node)
            return
        if not self._is_downloadable(node):
            return
        # If the user has marked items, prefer batch behaviour over the single
        # focused item. Otherwise download just this one.
        if self._marked:
            self.action_download_marked()
            return
        self._prompt_and_enqueue([(node.data or {}).get("item")])

    def action_toggle_mark(self) -> None:
        tree = self.query_one("#library", Tree)
        node = tree.cursor_node
        if node is None or not self._is_downloadable(node):
            return
        nid = node.id
        if nid in self._marked:
            original = self._marked.pop(nid)
            node.set_label(original)
        else:
            label = node.label.plain if hasattr(node.label, "plain") else str(node.label)
            self._marked[nid] = label
            node.set_label(f"[*] {label}")

    def action_download_marked(self) -> None:
        tree = self.query_one("#library", Tree)
        if not self._marked:
            # Fall back to the focused tree node if it's a downloadable item.
            node = tree.cursor_node
            if node is not None and self._is_downloadable(node):
                self._prompt_and_enqueue([(node.data or {}).get("item")])
                return
            self.notify("No items marked. Press Space to mark, or focus a movie/episode.",
                        severity="warning")
            return
        items: list[dict] = []
        for nid in list(self._marked.keys()):
            node = self._find_node_by_id(tree.root, nid)
            if node is None:
                continue
            item = (node.data or {}).get("item")
            if item is not None:
                items.append(item)
        if not items:
            self.notify("Marked items could not be resolved.", severity="warning")
            return
        self._prompt_and_enqueue(items, clear_marks=True)

    def _find_node_by_id(self, root, target_id):
        if root.id == target_id:
            return root
        for child in root.children:
            found = self._find_node_by_id(child, target_id)
            if found is not None:
                return found
        return None

    def _clear_marks(self) -> None:
        tree = self.query_one("#library", Tree)
        for nid, original in list(self._marked.items()):
            node = self._find_node_by_id(tree.root, nid)
            if node is not None:
                node.set_label(original)
        self._marked.clear()

    def _prompt_and_enqueue(self, items: list[dict], clear_marks: bool = False) -> None:
        valid = [it for it in items if it]
        if not valid:
            return
        if len(valid) == 1:
            summary = f"Download: {valid[0].get('Name', 'item')}"
        else:
            summary = f"Download {len(valid)} items"
        default_out = self.cfg.get("download_path", ".")
        default_audio = self.cfg.get("PreferredAudioLanguage", "eng")
        default_sub = self.cfg.get("PreferredSubtitleLanguage", "eng")

        def on_result(result):
            if result is None:
                return
            self._enqueue_items(
                valid,
                result["out_dir"],
                result["audio_lang"],
                result["sub_choice"],
            )
            if clear_marks:
                self._clear_marks()

        self.push_screen(
            DownloadPromptScreen(
                summary, default_out, default_audio, default_sub,
                valid, self.base, self.api_key, self.user_id,
            ),
            on_result,
        )

    def _enqueue_items(self, items: list[dict], out_dir: str,
                       audio_lang: str, sub_choice: str) -> None:
        out_dir_path = Path(out_dir).expanduser()
        try:
            out_dir_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            self.notify(f"Cannot create output directory: {e}", severity="error")
            return

        # Persist last-used output dir.
        self.cfg["download_path"] = out_dir
        try:
            save_config(self.cfg)
        except Exception:
            log.exception("Failed to persist download_path")

        for item in items:
            try:
                filename = filename_for(item)
            except Exception as e:
                log.exception("Could not determine filename for %s", item.get("Name"))
                self.notify(f"Skipped {item.get('Name')}: {e}", severity="error")
                continue
            spec = {
                "item": item,
                "filename": filename,
                "output_path": str(out_dir_path / filename),
                "audio_lang": audio_lang,
                "sub_choice": sub_choice,
            }
            self.manager.submit(spec)
        self.notify(f"Queued {len(items)} download(s).", severity="information")

    def _focused_job_id(self) -> str | None:
        table = self.query_one("#downloads", DataTable)
        if table.row_count == 0:
            return None
        try:
            coord = table.cursor_coordinate
            row_key = table.coordinate_to_cell_key(coord).row_key
        except Exception:
            return None
        return row_key.value if row_key is not None else None

    def action_cancel_job(self) -> None:
        job_id = self._focused_job_id()
        if job_id is None:
            self.notify("No download selected.", severity="warning")
            return
        self.manager.cancel(job_id)

    def action_remove_job(self) -> None:
        job_id = self._focused_job_id()
        if job_id is None:
            self.notify("No download selected.", severity="warning")
            return
        job = self.manager.get(job_id)
        if job is None:
            return
        if job.status not in (DONE, FAILED, CANCELLED):
            self.notify("Cancel the download first before removing.", severity="warning")
            return
        self.manager.remove(job_id)

    # ---------- Settings (in-tree) & Help ----------

    def action_settings(self) -> None:
        """Jump to the Settings branch in the library tree and expand it."""
        tree = self.query_one("#library", Tree)
        settings_node = next(
            (c for c in tree.root.children if (c.data or {}).get("kind") == "settings_root"),
            None,
        )
        if settings_node is None:
            return
        if not settings_node.is_expanded:
            settings_node.expand()
        tree.move_cursor(settings_node)
        tree.focus()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def _begin_setting_edit(self, leaf) -> None:
        data = leaf.data or {}
        key = data["key"]
        bar = self.query_one("#edit-bar", EditBar)
        bar.value = str(self.cfg.get(key, ""))
        bar.border_title = data["label"]
        bar.remove_class("hidden")
        bar.can_focus = True
        self._editing = {"leaf": leaf, "key": key, "label": data["label"], "type": data["type"]}
        bar.focus()

    def cancel_setting_edit(self) -> None:
        self._end_setting_edit()

    def _end_setting_edit(self) -> None:
        bar = self.query_one("#edit-bar", EditBar)
        bar.add_class("hidden")
        bar.can_focus = False
        bar.value = ""
        bar.border_title = ""
        self._editing = None
        try:
            self.query_one("#library", Tree).focus()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Modal screens get their own on_input_submitted; this only fires for
        # the App-level edit bar.
        if event.input.id != "edit-bar" or self._editing is None:
            return
        raw = event.value.strip()
        info = self._editing
        if info["type"] == "int":
            try:
                value = int(raw) if raw else 0
            except ValueError:
                self.notify(f"{info['label']}: not a number", severity="error")
                return
        else:
            value = raw
        self.cfg[info["key"]] = value
        if info["key"] == "VideoBitrate":
            self.cfg["MaxStreamingBitrate"] = value
        try:
            save_config(self.cfg)
        except Exception:
            log.exception("Failed to save config")
            self.notify("Failed to save settings", severity="error")
            return
        self._refresh_setting_leaf(info["leaf"])
        self._end_setting_edit()
        self.notify(f"{info['label']} saved.", severity="information")

    # ---------- Logging integration ----------

    def _install_log_handler(self) -> None:
        """Replace stdout log handlers with a TUI-aware one for the duration
        of the app. Saved handlers are restored on exit."""
        root = logging.getLogger("jellydown")
        self._saved_handlers = list(root.handlers)
        self._saved_propagate = root.propagate
        self._saved_level = root.level
        for h in self._saved_handlers:
            root.removeHandler(h)
        self._log_handler = _AppLogHandler(self)
        self._log_handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(self._log_handler)
        root.propagate = False
        if root.level == logging.NOTSET or root.level > logging.INFO:
            root.setLevel(logging.INFO)

    def _restore_log_handler(self) -> None:
        root = logging.getLogger("jellydown")
        if getattr(self, "_log_handler", None) is not None:
            try:
                root.removeHandler(self._log_handler)
            except Exception:
                pass
        for h in getattr(self, "_saved_handlers", []):
            root.addHandler(h)
        root.propagate = getattr(self, "_saved_propagate", False)
        if hasattr(self, "_saved_level"):
            root.setLevel(self._saved_level)

    # ---------- Lifecycle ----------

    async def on_unmount(self) -> None:
        # Cancel any in-flight downloads when the app exits.
        try:
            self.manager.shutdown(wait=False)
        except Exception:
            log.exception("Error shutting down download manager")
        self._restore_log_handler()


def run(base: str, api_key: str, user_id: str, cfg: dict) -> None:
    JellydownApp(base, api_key, user_id, cfg).run()
