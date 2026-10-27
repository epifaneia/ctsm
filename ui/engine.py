"""engine — puente entre la interfaz y el pipeline de CTSM. No reimplementa nada.

Dos modos, la misma instantánea para el frontend:

  · live: cada trabajo es un sandbox jobs/<id>/data (CTSM_DATA_DIR) con el ReqIF y
    los PDFs subidos. Lanza `run.py` como subproceso y lee el progreso de los
    artefactos que el pipeline va dejando: s4 reescribe su checkpoint tras cada
    requisito, así que el avance se ve requisito a requisito.
  · demo: reproduce una ejecución real grabada en ui/demo/<nombre>/ (la graba
    tools/grabar_demo.py). Mismos veredictos, mismas citas, mismos tiempos
    relativos, acelerados y declarados como tales. No necesita modelo ni red.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

UI_DIR = Path(__file__).resolve().parent
ROOT = UI_DIR.parent
JOBS_DIR = UI_DIR / "jobs"
DEMO_DIR = UI_DIR / "demo"

# Pasos del pipeline, en orden, con el paso de diseño (1..5) al que pertenecen.
STEPS = [
    ("s0_prepare_stk", 1), ("s1_parse_stk", 1), ("s2_supplier_corpus", 1),
    ("s3_retrieve", 2), ("s4_schema", 3), ("s4_evaluate", 4),
    ("s6_verify", 5), ("s7_inject", 5),
]

JOBS: dict[str, "Job"] = {}


def _slug(name: str) -> str:
    """El mismo stem que usa run.py."""
    return re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_")


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _requirement_texts(stk: dict | None) -> dict[str, str]:
    if not stk:
        return {}
    return {o["identifier"]: (o.get("text") or "") for o in stk.get("objects", [])}


def _rows(results: dict | None, texts: dict[str, str], truth: dict[str, str]) -> list[dict]:
    rows = []
    for r in (results or {}).get("results", []):
        rid = r.get("oem_req_id") or r["spec_object_id"]
        text = texts.get(r["spec_object_id"], "")
        # la primera línea de ReqIF.Text repite el id: fuera para mostrar
        if text.startswith(rid):
            text = text[len(rid):].strip()
        rows.append({"id": rid, "text": text, "status": r["status"],
                     "rationale": r.get("rationale", ""), "comments": r.get("comments", ""),
                     "evidence": r.get("evidence") or [], "flags": r.get("flags") or [],
                     "expected": truth.get(rid)})
    return rows


class Job:
    def __init__(self, mode: str, stem: str, total: int):
        self.id = uuid.uuid4().hex[:12]
        self.mode = mode
        self.stem = stem
        self.total = total
        self.started = time.time()
        self.status = "running"
        self.error = ""
        self.lock = threading.Lock()

    # implementado por cada modo
    def step_states(self) -> tuple[dict[str, str], int]:
        raise NotImplementedError

    def rows(self) -> list[dict]:
        raise NotImplementedError

    def custody(self) -> dict:
        raise NotImplementedError

    def snapshot(self) -> dict:
        states, s4_done = self.step_states()
        return {"id": self.id, "mode": self.mode, "stem": self.stem, "status": self.status,
                "error": self.error, "elapsed": round(time.time() - self.started, 1),
                "steps": [{"name": n, "design": d, "state": states[n]} for n, d in STEPS],
                "s4_done": s4_done, "s4_total": self.total,
                "rows": self.rows() if self.status == "done" else self.partial_rows(),
                "custody": self.custody()}

    def partial_rows(self) -> list[dict]:
        return []


# ── modo live ────────────────────────────────────────────────────────────────

class LiveJob(Job):
    def __init__(self, reqif: tuple[str, bytes], pdfs: list[tuple[str, bytes]]):
        name = Path(reqif[0]).name
        super().__init__("live", _slug(Path(name).stem), 0)
        self.dir = JOBS_DIR / self.id
        self.data = self.dir / "data"
        stk_dir = self.data / "inputs" / "stk_reqif"
        sup_dir = self.data / "inputs" / "supplier_docs"
        stk_dir.mkdir(parents=True)
        sup_dir.mkdir(parents=True)
        (stk_dir / name).write_bytes(reqif[1])
        for pname, content in pdfs:
            (sup_dir / Path(pname).name).write_bytes(content)
        self.reqif_name = name
        self.ledger = self.dir / "custody.jsonl"
        self.log: list[str] = []
        threading.Thread(target=self._run, daemon=True).start()

    def _p(self, *parts: str) -> Path:
        return self.data.joinpath(*parts)

    def _run(self) -> None:
        env = dict(os.environ, PYTHONIOENCODING="utf-8", CTSM_DATA_DIR=str(self.data),
                   CUSTODIA_LEDGER=str(self.ledger))
        try:
            proc = subprocess.Popen([sys.executable, "-u", str(ROOT / "run.py"), self.stem],
                                    cwd=str(ROOT), env=env, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT, text=True, encoding="utf-8")
            for line in proc.stdout:
                with self.lock:
                    self.log.append(line.rstrip())
            proc.wait()
            ok = proc.returncode == 0 and self._p("outputs", "reqif", self.reqif_name).is_file()
            with self.lock:
                self.status = "done" if ok else "error"
                if not ok:
                    self.error = next((l for l in reversed(self.log) if l.strip()), "el pipeline falló")
        except Exception as e:  # noqa: BLE001
            with self.lock:
                self.status, self.error = "error", str(e)

    def step_states(self):
        stem = self.stem
        evid = _read_json(self._p("interim", "evidence", f"{stem}.json"))
        if evid is not None:
            self.total = len(evid)
        ev = _read_json(self._p("interim", "eval", f"{stem}.json")) or []
        done = {
            "s0_prepare_stk": self._p("interim", "stk_prepared", self.reqif_name).is_file(),
            "s1_parse_stk": self._p("interim", "stk_json", f"{stem}.json").is_file(),
            "s2_supplier_corpus": self._p("interim", "corpus", "corpus.json").is_file(),
            "s3_retrieve": evid is not None,
            "s4_schema": evid is not None,
            "s4_evaluate": self._p("interim", "results", f"{stem}.json").is_file()
                           or (self.total > 0 and len(ev) >= self.total),
            "s6_verify": self._p("interim", "results", f"{stem}.json").is_file(),
            "s7_inject": self._p("outputs", "reqif", self.reqif_name).is_file(),
        }
        # el primer paso sin terminar es el que corre (o el que falló)
        states, current = {}, None
        for name, _ in STEPS:
            if done[name]:
                states[name] = "done"
            elif current is None:
                current = name
                states[name] = {"running": "running", "error": "error"}.get(self.status, "pending")
            else:
                states[name] = "pending"
        return states, len(ev)

    def _texts(self):
        return _requirement_texts(_read_json(self._p("interim", "stk_json", f"{self.stem}.json")))

    def rows(self):
        return _rows(_read_json(self._p("interim", "results", f"{self.stem}.json")), self._texts(), {})

    def partial_rows(self):
        # veredictos crudos de s4 según llegan: aún sin verificar por s6
        ev = _read_json(self._p("interim", "eval", f"{self.stem}.json")) or []
        rows = _rows({"results": ev}, self._texts(), {})
        for r in rows:
            r["unverified"] = True
        return rows

    def custody(self):
        calls = left = 0
        secs = 0.0
        if self.ledger.is_file():
            for line in self.ledger.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                calls += 1
                left += bool(e.get("leaves_machine"))
                secs += float(e.get("seconds") or 0)
        return {"calls": calls, "left_machine": left, "model_seconds": round(secs, 1)}

    def supplier_dir(self) -> Path:
        return self._p("inputs", "supplier_docs")

    def output_reqif(self) -> Path | None:
        p = self._p("outputs", "reqif", self.reqif_name)
        return p if p.is_file() else None

    def prepared_reqif(self) -> Path | None:
        p = self._p("interim", "stk_prepared", self.reqif_name)
        return p if p.is_file() else None


# ── modo demo ────────────────────────────────────────────────────────────────

class DemoJob(Job):
    """Reproduce una ejecución grabada. El reloj de la reproducción se comprime:
    cada paso dura lo mismo que en la ejecución real dividido por `speed`, con un
    mínimo para que se vea. Los veredictos y las citas son los grabados, tal cual."""

    MIN_STEP = 0.6

    def __init__(self, name: str, speed: float):
        rec = load_demo(name)
        if rec is None:
            raise ValueError(f"no hay demo grabada '{name}'")
        self.rec = rec
        super().__init__("demo", rec["stem"], len(rec["results"]["results"]))
        self.speed = max(1.0, speed)
        t, self.schedule = 0.0, {}
        for name_, _ in STEPS:
            if name_ == "s4_evaluate":
                ends = []
                for s in rec["timeline"]["s4_per_requirement"]:
                    t += max(self.MIN_STEP, s / self.speed)
                    ends.append(t)
                self.s4_ends = ends
            else:
                t += max(self.MIN_STEP, rec["timeline"]["steps"].get(name_, 0.2) / self.speed)
            self.schedule[name_] = t
        self.duration = t

    def _t(self) -> float:
        return time.time() - self.started

    def step_states(self):
        t = self._t()
        if t >= self.duration:
            self.status = "done"
        states, prev_end = {}, 0.0
        for name, _ in STEPS:
            end = self.schedule[name]
            states[name] = "done" if t >= end else ("running" if t >= prev_end else "pending")
            prev_end = end
        return states, sum(1 for e in self.s4_ends if t >= e)

    def _all_rows(self):
        return _rows(self.rec["results"], _requirement_texts(self.rec["stk"]), self.rec.get("truth", {}))

    def rows(self):
        return self._all_rows()

    def partial_rows(self):
        _, n = self.step_states()
        rows = self._all_rows()[:n]
        for r in rows:
            r["unverified"] = True
        return rows

    def custody(self):
        c = dict(self.rec["timeline"]["custody"])
        _, n = self.step_states()
        frac = n / self.total if self.total else 1
        c["calls"] = round(c["calls"] * frac)
        return c

    def supplier_dir(self) -> Path:
        import config  # noqa: E402  (ROOT está en sys.path desde app.py)
        return config.SUPPLIER_DOCS_DIR

    def output_reqif(self):
        return None

    def prepared_reqif(self):
        return None


def load_demo(name: str) -> dict | None:
    d = DEMO_DIR / name
    if not (d / "results.json").is_file():
        return None
    return {"stem": _read_json(d / "timeline.json")["stem"],
            "results": _read_json(d / "results.json"), "stk": _read_json(d / "stk.json"),
            "timeline": _read_json(d / "timeline.json"), "truth": _read_json(d / "truth.json") or {}}


def available_demos() -> list[dict]:
    out = []
    for d in sorted(DEMO_DIR.glob("*/timeline.json")):
        tl = _read_json(d) or {}
        out.append({"name": d.parent.name, **{k: tl.get(k) for k in
                    ("stem", "reqif", "supplier_docs", "engine", "recorded", "machine", "total_seconds")}})
    return out


def create_live(reqif, pdfs) -> Job:
    job = LiveJob(reqif, pdfs)
    JOBS[job.id] = job
    return job


def create_demo(name: str, speed: float) -> Job:
    job = DemoJob(name, speed)
    JOBS[job.id] = job
    return job
