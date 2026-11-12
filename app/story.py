"""
🎬 Сюжетные миссии — важные события жизни, как в GTA.

  • миссия: название, зачем она тебе, XP за финал, этапы (у каждого — немного XP);
  • этап выполнен → XP сразу; финал → катсцена «МИССИЯ ПРОЙДЕНА», твоя фраза-итог, респект +1;
  • миссию можно отложить, но не провалить: жизнь и так непростая;
  • пройденные миссии складываются в хронику по главам («Глава 2: Второй курс»).
"""

from datetime import date, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS story_chapters (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    title   TEXT NOT NULL,
    started TEXT NOT NULL,
    ended   TEXT
);
CREATE TABLE IF NOT EXISTS story_missions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER,                      -- глава, в которой пройдена
    title      TEXT    NOT NULL,
    emoji      TEXT    NOT NULL DEFAULT '🎬',
    why        TEXT    NOT NULL DEFAULT '',  -- зачем это тебе
    xp         INTEGER NOT NULL,
    status     TEXT    NOT NULL DEFAULT 'active',   -- active / paused / done
    created    TEXT    NOT NULL,
    done_day   TEXT,
    outro      TEXT    NOT NULL DEFAULT '',  -- фраза-итог для катсцены и хроники
    quest_id   INTEGER
);
CREATE TABLE IF NOT EXISTS story_steps (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    mission_id INTEGER NOT NULL,
    title      TEXT    NOT NULL,
    xp         INTEGER NOT NULL DEFAULT 100,
    ord        INTEGER NOT NULL DEFAULT 0,
    done_day   TEXT,
    quest_id   INTEGER
);
"""

DEFAULT_XP = 1000
STEP_XP = 100


class StoryError(Exception):
    pass


class Story:
    def __init__(self, game):
        self.g = game
        self.conn = game.conn

    def _now(self) -> str:
        return datetime.now(self.g.tz).replace(tzinfo=None).isoformat(timespec="seconds")

    def _done_quest(self, day: date, title: str, xp: int) -> int:
        cur = self.conn.execute(
            "INSERT INTO quests (day, category, title, xp, status, done_at) VALUES (?, 'story', ?, ?, 'done', ?)",
            (day.isoformat(), title[:200], xp, self._now()))
        return cur.lastrowid

    # ---------- главы ----------

    def chapter(self, today: date) -> dict:
        r = self.conn.execute("SELECT * FROM story_chapters WHERE ended IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        if r is None:
            cur = self.conn.execute("INSERT INTO story_chapters (title, started) VALUES ('Глава 1', ?)",
                                    (today.isoformat(),))
            self.conn.commit()
            r = self.conn.execute("SELECT * FROM story_chapters WHERE id = ?", (cur.lastrowid,)).fetchone()
        return dict(r)

    def new_chapter(self, title: str, today: date) -> dict:
        title = title.strip()
        if not title:
            raise StoryError("Назови главу: «Глава 2: Второй курс»")
        cur = self.chapter(today)
        self.conn.execute("UPDATE story_chapters SET ended = ? WHERE id = ?", (today.isoformat(), cur["id"]))
        self.conn.execute("INSERT INTO story_chapters (title, started) VALUES (?, ?)", (title[:80], today.isoformat()))
        self.conn.commit()
        return self.chapter(today)

    def rename_chapter(self, title: str, today: date) -> dict:
        if not title.strip():
            raise StoryError("Пустое название")
        cur = self.chapter(today)
        self.conn.execute("UPDATE story_chapters SET title = ? WHERE id = ?", (title.strip()[:80], cur["id"]))
        self.conn.commit()
        return self.chapter(today)

    # ---------- миссии ----------

    def add(self, title: str, today: date, xp: int = DEFAULT_XP, why: str = "", emoji: str = "🎬",
            steps: list | None = None) -> dict:
        title = title.strip()
        if not title:
            raise StoryError("Как называется миссия?")
        if not 0 < xp <= 20000:
            raise StoryError("XP за финал — от 1 до 20 000")
        cur = self.conn.execute(
            "INSERT INTO story_missions (title, emoji, why, xp, created) VALUES (?, ?, ?, ?, ?)",
            (title[:120], (emoji or "🎬")[:4], why.strip()[:300], xp, today.isoformat()))
        mid = cur.lastrowid
        for i, st in enumerate(steps or []):
            t, sx = (st, STEP_XP) if isinstance(st, str) else (st[0], st[1])
            if t.strip():
                self.conn.execute("INSERT INTO story_steps (mission_id, title, xp, ord) VALUES (?, ?, ?, ?)",
                                  (mid, t.strip()[:120], sx, i))
        self.conn.commit()
        return self.get(mid)

    def get(self, mid: int) -> dict:
        r = self.conn.execute("SELECT * FROM story_missions WHERE id = ?", (mid,)).fetchone()
        if r is None:
            raise StoryError("Такой миссии нет")
        m = dict(r)
        m["steps"] = [dict(s) for s in self.conn.execute(
            "SELECT * FROM story_steps WHERE mission_id = ? ORDER BY ord, id", (mid,))]
        done = sum(1 for s in m["steps"] if s["done_day"])
        m["steps_done"], m["steps_total"] = done, len(m["steps"])
        m["next_step"] = next((s for s in m["steps"] if not s["done_day"]), None)
        m["xp_steps"] = sum(s["xp"] for s in m["steps"] if s["done_day"])
        return m

    def edit(self, mid: int, title: str | None = None, xp: int | None = None, why: str | None = None,
             emoji: str | None = None) -> dict:
        m = self.get(mid)
        if m["status"] == "done":
            raise StoryError("Пройденную миссию уже не поменять — она в хронике")
        if xp is not None and not 0 < xp <= 20000:
            raise StoryError("XP за финал — от 1 до 20 000")
        self.conn.execute("UPDATE story_missions SET title=?, xp=?, why=?, emoji=? WHERE id=?",
                          ((title or m["title"]).strip()[:120], xp or m["xp"],
                           m["why"] if why is None else why.strip()[:300], (emoji or m["emoji"])[:4], mid))
        self.conn.commit()
        return self.get(mid)

    def delete(self, mid: int) -> None:
        m = self.get(mid)
        if m["status"] == "done":
            raise StoryError("Пройденная миссия — часть хроники, её не удалить")
        # XP за уже выполненные этапы остаётся (это обычные квесты в истории)
        self.conn.execute("DELETE FROM story_steps WHERE mission_id = ?", (mid,))
        self.conn.execute("DELETE FROM story_missions WHERE id = ?", (mid,))
        self.conn.commit()

    def set_paused(self, mid: int, paused: bool) -> dict:
        m = self.get(mid)
        if m["status"] == "done":
            raise StoryError("Миссия уже пройдена")
        self.conn.execute("UPDATE story_missions SET status = ? WHERE id = ?", ("paused" if paused else "active", mid))
        self.conn.commit()
        return self.get(mid)

    def missions(self, status: str | None = None) -> list[dict]:
        q = "SELECT id FROM story_missions" + (" WHERE status = ?" if status else "") + " ORDER BY id"
        return [self.get(r["id"]) for r in self.conn.execute(q, (status,) if status else ())]

    # ---------- этапы ----------

    def add_step(self, mid: int, title: str, xp: int = STEP_XP) -> dict:
        m = self.get(mid)
        if m["status"] == "done":
            raise StoryError("Миссия уже пройдена")
        if not title.strip():
            raise StoryError("Что за этап?")
        if not 0 <= xp <= 5000:
            raise StoryError("XP за этап — от 0 до 5000")
        self.conn.execute("INSERT INTO story_steps (mission_id, title, xp, ord) VALUES (?, ?, ?, ?)",
                          (mid, title.strip()[:120], xp, len(m["steps"])))
        self.conn.commit()
        return self.get(mid)

    def _step(self, sid: int) -> dict:
        r = self.conn.execute("SELECT * FROM story_steps WHERE id = ?", (sid,)).fetchone()
        if r is None:
            raise StoryError("Такого этапа нет")
        return dict(r)

    def toggle_step(self, sid: int, today: date) -> dict:
        s = self._step(sid)
        m = self.get(s["mission_id"])
        if m["status"] == "done":
            raise StoryError("Миссия уже пройдена")
        if s["done_day"]:
            if s["quest_id"]:
                self.conn.execute("DELETE FROM quests WHERE id = ?", (s["quest_id"],))
            self.conn.execute("UPDATE story_steps SET done_day = NULL, quest_id = NULL WHERE id = ?", (sid,))
        else:
            qid = self._done_quest(today, f"{m['emoji']} {m['title']}: {s['title']}", s["xp"]) if s["xp"] else None
            self.conn.execute("UPDATE story_steps SET done_day = ?, quest_id = ? WHERE id = ?",
                              (today.isoformat(), qid, sid))
            if m["status"] == "paused":
                self.conn.execute("UPDATE story_missions SET status = 'active' WHERE id = ?", (m["id"],))
        self.conn.commit()
        return self.get(m["id"])

    def delete_step(self, sid: int) -> dict:
        s = self._step(sid)
        if s["done_day"]:
            raise StoryError("Выполненный этап сначала отметь обратно")
        self.conn.execute("DELETE FROM story_steps WHERE id = ?", (sid,))
        self.conn.commit()
        return self.get(s["mission_id"])

    # ---------- финал ----------

    def complete(self, mid: int, today: date, outro: str = "") -> dict:
        m = self.get(mid)
        if m["status"] == "done":
            raise StoryError("Миссия уже пройдена")
        ch = self.chapter(today)
        qid = self._done_quest(today, f"{m['emoji']} Миссия пройдена: {m['title']}", m["xp"])
        self.conn.execute(
            "UPDATE story_missions SET status='done', done_day=?, outro=?, quest_id=?, chapter_id=? WHERE id=?",
            (today.isoformat(), outro.strip()[:200], qid, ch["id"], mid))
        self.conn.commit()
        r = self.get(mid)
        r["chapter"] = ch["title"]
        r["respect"] = self.respect()
        return r

    def respect(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM story_missions WHERE status='done'").fetchone()[0]

    # ---------- хроника ----------

    def chronicle(self, today: date) -> list[dict]:
        cur = self.chapter(today)
        out = []
        for c in self.conn.execute("SELECT * FROM story_chapters ORDER BY id DESC"):
            ms = [self.get(r["id"]) for r in self.conn.execute(
                "SELECT id FROM story_missions WHERE chapter_id = ? AND status='done' ORDER BY done_day DESC, id DESC",
                (c["id"],))]
            out.append({**dict(c), "current": c["id"] == cur["id"], "missions": ms,
                        "xp": sum(m["xp"] + m["xp_steps"] for m in ms)})
        return out

    def counts(self) -> dict:
        q = lambda sql: self.conn.execute(sql).fetchone()[0]
        return {"story_done": q("SELECT COUNT(*) FROM story_missions WHERE status='done'"),
                "story_big": q("SELECT COUNT(*) FROM story_missions m WHERE status='done' AND "
                               "(SELECT COUNT(*) FROM story_steps s WHERE s.mission_id=m.id AND s.done_day IS NOT NULL) >= 3"),
                "chapters_closed": q("SELECT COUNT(*) FROM story_chapters c WHERE ended IS NOT NULL AND EXISTS "
                                     "(SELECT 1 FROM story_missions m WHERE m.chapter_id=c.id AND m.status='done')")}
