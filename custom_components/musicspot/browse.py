"""Browse model: turns the Spotify library into pages for a panel (design C).

Each panel has its own Browser: a tab (PLAYLISTS / ALBUMS / ARTISTS / RECENT, D21)
plus a path stack for drilling into a playlist, album or artist. The panel only sees
row numbers (D11); rows keep the Spotify URIs needed to open, play or queue them.
Lists show 6 rows; the Albums tab root is a 4×2 cover grid (D26). Folders start with
a "Play all" row so the whole context can be played (D16).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from .api import MusicSpotApi, SpotifyForbiddenError, SpotifyNotFoundError

LIST_SIZE = 6
GRID_SIZE = 8
TABS = ("playlists", "albums", "artists", "recent")
_CURSOR_LIMIT = 50


@dataclass
class Node:
    """A level in the browse tree."""

    kind: str  # playlists | albums | artists | recent | playlist | album | artist | liked
    title: str
    id: str = ""
    context_uri: str = ""  # what "Play all" plays, and the context for its tracks
    image: str | None = None  # cover reused for rows without their own image
    page: int = 1
    cache: list[dict[str, Any]] | None = None  # cursor-based lists, fetched once
    notice: str = ""  # subtitle of the Play all row

    @property
    def grid(self) -> bool:
        """The Albums tab root is a cover grid."""
        return self.kind == "albums"

    @property
    def page_size(self) -> int:
        """Rows per page."""
        return GRID_SIZE if self.grid else LIST_SIZE


@dataclass
class Row:
    """One row (or grid tile) on the panel."""

    title: str
    subtitle: str = ""
    count: str = ""  # right column: track count or duration
    image: str | None = None
    open: Node | None = None  # folder: drill in
    uri: str = ""  # playable item (track/episode)
    context_uri: str = ""  # play `uri` inside this context; or the context itself
    play_all: bool = False
    album_uri: str = ""  # grid: to mark the album that is playing


@dataclass
class Page:
    """What `show_page` needs."""

    title: str
    tab: int
    page: int
    pages: int
    can_back: bool
    grid: bool
    first_number: int  # number shown on the first numbered row
    rows: list[Row] = field(default_factory=list)


def _pick_image(images: list[dict[str, Any]] | None, size: int) -> str | None:
    """Smallest image at least `size` px (Spotify sends 640/300/64)."""
    candidates = [i for i in images or [] if i.get("url")]
    if not candidates:
        return None
    big_enough = [i for i in candidates if (i.get("width") or 0) >= size]
    if big_enough:
        return min(big_enough, key=lambda i: i.get("width") or 0)["url"]
    return max(candidates, key=lambda i: i.get("width") or 0)["url"]


def _duration(ms: int | None) -> str:
    """m:ss."""
    s = int((ms or 0) / 1000)
    return f"{s // 60}:{s % 60:02d}" if ms else ""


def _track_row(track: dict[str, Any] | None, context_uri: str, fallback_image: str | None) -> Row | None:
    """Row for a track or episode object (None for unavailable/local items)."""
    if not track or not track.get("uri"):
        return None
    if track.get("type") == "episode":
        subtitle = (track.get("show") or {}).get("name", "")
        image = _pick_image(track.get("images"), 40) or fallback_image
    else:
        subtitle = ", ".join(a.get("name", "") for a in track.get("artists", []))
        image = _pick_image((track.get("album") or {}).get("images"), 40) or fallback_image
    return Row(
        title=track.get("name", "?"),
        subtitle=subtitle,
        count=_duration(track.get("duration_ms")),
        image=image,
        uri=track["uri"],
        context_uri=context_uri,
    )


def _album_open(album: dict[str, Any]) -> Node:
    return Node(
        "album",
        album.get("name") or "Album",
        id=album["id"],
        context_uri=album.get("uri") or f"spotify:album:{album['id']}",
        image=_pick_image(album.get("images"), 40),
    )


class Browser:
    """Browse state for one panel."""

    def __init__(self, api: MusicSpotApi, user_id: str) -> None:
        """Start on the Playlists tab."""
        self._api = api
        self._user_id = user_id
        self._tab = 0
        self._stack: list[Node] = [self._tab_root(0)]
        self._liked_total: int | None = None
        self.rows: list[Row] = []

    @staticmethod
    def _tab_root(tab: int) -> Node:
        kind = TABS[tab]
        return Node(kind, kind.upper())

    @property
    def node(self) -> Node:
        """Current level."""
        return self._stack[-1]

    def select_tab(self, tab: int) -> None:
        """Switch tab (resets to its root)."""
        if 0 <= tab < len(TABS):
            self._tab = tab
            self._stack = [self._tab_root(tab)]

    def invalidate_liked(self) -> None:
        """Liked Songs changed: refresh its count next time."""
        self._liked_total = None

    def open(self, node: Node) -> None:
        """Drill into a folder."""
        self._stack.append(node)

    def back(self) -> bool:
        """Go up one level; False at a tab root."""
        if len(self._stack) == 1:
            return False
        self._stack.pop()
        return True

    def turn_page(self, delta: int) -> None:
        """Move to the previous/next page (clamped when loading)."""
        self.node.page = max(1, self.node.page + delta)

    async def async_load(self) -> Page:
        """Fetch the current page from Spotify."""
        node = self.node
        loader = getattr(self, f"_load_{node.kind}")
        rows, total, header = await loader(node)
        pages = max(1, math.ceil(total / node.page_size))
        if node.page > pages:
            node.page = pages
            rows, total, header = await loader(node)
        self.rows = rows
        start = (node.page - 1) * node.page_size
        return Page(
            title=node.title,
            tab=self._tab,
            page=node.page,
            pages=pages,
            can_back=len(self._stack) > 1,
            grid=node.grid,
            first_number=max(1, start - header + 1),
            rows=rows,
        )

    # ---- paging helpers -------------------------------------------------

    @staticmethod
    def _window(node: Node, header_rows: int) -> tuple[int, int, int]:
        """For the current page return (header rows shown, API offset, API limit).

        The virtual list is `header_rows` fixed rows followed by the API items.
        """
        size = node.page_size
        start = (node.page - 1) * size
        end = start + size
        header = max(0, min(end, header_rows) - start)
        offset = max(0, start - header_rows)
        return header, offset, size - header

    def _play_row(self, node: Node) -> Row:
        return Row(
            title="Play all",
            subtitle=node.notice,
            image=node.image,
            context_uri=node.context_uri,
            play_all=True,
        )

    async def _liked_count(self) -> int:
        if self._liked_total is None:
            data = await self._api.get_saved_tracks(1, 0)
            self._liked_total = int(data.get("total") or 0)
        return self._liked_total

    # ---- loaders: return (rows, virtual total, header rows) ---------------

    async def _load_playlists(self, node: Node) -> tuple[list[Row], int, int]:
        header, offset, limit = self._window(node, 1)
        rows: list[Row] = []
        if header:
            liked = await self._liked_count()
            rows.append(
                Row(
                    "Liked Songs",
                    count=f"{liked:03d}",
                    open=Node(
                        "liked",
                        "Liked Songs",
                        context_uri=f"spotify:user:{self._user_id}:collection",
                    ),
                )
            )
        data = await self._api.get_playlists(limit, offset)
        for pl in data.get("items") or []:
            if not pl or not pl.get("id"):
                continue
            count = (pl.get("items") or pl.get("tracks") or {}).get("total")
            image = _pick_image(pl.get("images"), 40)
            rows.append(
                Row(
                    title=pl.get("name") or "?",
                    count=f"{count:03d}" if count is not None else "",
                    image=image,
                    open=Node(
                        "playlist",
                        pl.get("name") or "Playlist",
                        id=pl["id"],
                        context_uri=pl.get("uri") or f"spotify:playlist:{pl['id']}",
                        image=image,
                    ),
                )
            )
        return rows, 1 + int(data.get("total") or 0), 0

    async def _load_albums(self, node: Node) -> tuple[list[Row], int, int]:
        _, offset, limit = self._window(node, 0)
        data = await self._api.get_saved_albums(limit, offset)
        rows = []
        for entry in data.get("items") or []:
            album = (entry or {}).get("album") or {}
            if not album.get("id"):
                continue
            rows.append(
                Row(
                    title=album.get("name") or "?",
                    subtitle=", ".join(a.get("name", "") for a in album.get("artists", [])),
                    image=_pick_image(album.get("images"), 84),
                    open=_album_open(album),
                    album_uri=album.get("uri") or "",
                )
            )
        return rows, int(data.get("total") or len(rows)), 0

    async def _load_artists(self, node: Node) -> tuple[list[Row], int, int]:
        if node.cache is None:
            node.cache = []
            after = None
            while len(node.cache) < 200:
                data = await self._api.get_followed_artists(_CURSOR_LIMIT, after)
                node.cache.extend(a for a in data.get("items") or [] if a and a.get("id"))
                after = (data.get("cursors") or {}).get("after")
                if not after:
                    break
        start = (node.page - 1) * LIST_SIZE
        rows = []
        for artist in node.cache[start : start + LIST_SIZE]:
            image = _pick_image(artist.get("images"), 40)
            rows.append(
                Row(
                    title=artist.get("name") or "?",
                    image=image,
                    open=Node(
                        "artist",
                        artist.get("name") or "Artist",
                        id=artist["id"],
                        context_uri=artist.get("uri") or f"spotify:artist:{artist['id']}",
                        image=image,
                    ),
                )
            )
        return rows, len(node.cache), 0

    async def _load_recent(self, node: Node) -> tuple[list[Row], int, int]:
        if node.cache is None:
            data = await self._api.get_recently_played(_CURSOR_LIMIT)
            seen: set[str] = set()
            node.cache = []
            for entry in data.get("items") or []:
                track = (entry or {}).get("track") or {}
                if track.get("uri") and track["uri"] not in seen:
                    seen.add(track["uri"])
                    node.cache.append(entry)
        start = (node.page - 1) * LIST_SIZE
        rows = []
        for entry in node.cache[start : start + LIST_SIZE]:
            context = (entry.get("context") or {}).get("uri") or ""
            row = _track_row(entry.get("track"), context, None)
            if row:
                rows.append(row)
        return rows, len(node.cache), 0

    async def _load_liked(self, node: Node) -> tuple[list[Row], int, int]:
        header, offset, limit = self._window(node, 1)
        rows = [self._play_row(node)] if header else []
        data = await self._api.get_saved_tracks(limit, offset)
        for entry in data.get("items") or []:
            row = _track_row((entry or {}).get("track"), node.context_uri, None)
            if row:
                rows.append(row)
        return rows, 1 + int(data.get("total") or 0), 1

    async def _load_playlist(self, node: Node) -> tuple[list[Row], int, int]:
        header, offset, limit = self._window(node, 1)
        rows = [self._play_row(node)] if header else []
        try:
            data = await self._api.get_playlist_items(node.id, limit, offset)
        except (SpotifyForbiddenError, SpotifyNotFoundError):
            # Since Feb 2026 only owned/collaborative playlists list their items.
            node.notice = "Spotify only lists songs of your own playlists"
            return [self._play_row(node)], 1, 1
        for entry in data.get("items") or []:
            row = _track_row(
                (entry or {}).get("item") or (entry or {}).get("track"),
                node.context_uri,
                node.image,
            )
            if row:
                rows.append(row)
        return rows, 1 + int(data.get("total") or 0), 1

    async def _load_album(self, node: Node) -> tuple[list[Row], int, int]:
        header, offset, limit = self._window(node, 1)
        rows = [self._play_row(node)] if header else []
        data = await self._api.get_album_tracks(node.id, limit, offset)
        for track in data.get("items") or []:
            row = _track_row(track, node.context_uri, node.image)
            if row:
                rows.append(row)
        return rows, 1 + int(data.get("total") or 0), 1

    async def _load_artist(self, node: Node) -> tuple[list[Row], int, int]:
        header, offset, limit = self._window(node, 1)
        rows = [self._play_row(node)] if header else []
        data = await self._api.get_artist_albums(node.id, limit, offset)
        for album in data.get("items") or []:
            if album and album.get("id"):
                rows.append(
                    Row(
                        title=album.get("name") or "?",
                        subtitle=(album.get("release_date") or "")[:4],
                        count=f"{album.get('total_tracks'):03d}" if album.get("total_tracks") else "",
                        image=_pick_image(album.get("images"), 40),
                        open=_album_open(album),
                    )
                )
        return rows, 1 + int(data.get("total") or 0), 1
