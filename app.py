"""
Real Estate Parser — Flask backend
Запуск: python app.py  ->  http://localhost:5050
"""
import sys
import os

# Гарантируем что Python ищет пакеты в папке самого app.py
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import threading
import time
from datetime import datetime, timezone

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS

from site_parsers import get_parser, list_parsers

# Абсолютные пути к templates/ и static/ — работает независимо
# от того, из какой папки запускается скрипт
app = Flask(
    __name__,
    template_folder=os.path.join(_HERE, "templates"),
    static_folder=os.path.join(_HERE, "static"),
)
CORS(app)

# ── In-memory хранилище заданий ───────────────────────────────────────────────
jobs: dict    = {}   # job_id -> метаданные задания
results: dict = {}   # job_id -> список объявлений


def _run_job(job_id: str, sources: list, filters: dict):
    jobs[job_id]["status"]     = "running"
    jobs[job_id]["started_at"] = datetime.now(timezone.utc).isoformat()
    all_listings = []

    for source_key in sources:
        parser = get_parser(source_key)
        if parser is None:
            jobs[job_id]["errors"].append(f"Неизвестный парсер: {source_key}")
            continue
        try:
            lst = parser.parse(filters)
            all_listings.extend(lst)
            jobs[job_id]["progress"][source_key] = len(lst)
        except Exception as e:
            jobs[job_id]["errors"].append(f"{source_key}: {e}")

    results[job_id]              = all_listings
    jobs[job_id]["status"]       = "done"
    jobs[job_id]["finished_at"]  = datetime.now(timezone.utc).isoformat()
    jobs[job_id]["total"]        = len(all_listings)


# ── Маршруты ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/parsers")
def api_parsers():
    """Список зарегистрированных парсеров."""
    return jsonify(list_parsers())


@app.route("/api/parse", methods=["POST"])
def api_parse():
    """Запустить новое задание парсинга."""
    data    = request.json or {}
    sources = data.get("sources", [p["key"] for p in list_parsers()])
    filters = data.get("filters", {})

    if not sources:
        return jsonify({"error": "Не выбрано ни одного источника"}), 400

    job_id = f"job_{int(time.time() * 1000)}"
    jobs[job_id] = {
        "id":          job_id,
        "status":      "pending",
        "sources":     sources,
        "filters":     filters,
        "created_at":  datetime.now(timezone.utc).isoformat(),
        "started_at":  None,
        "finished_at": None,
        "total":       0,
        "progress":    {},
        "errors":      [],
    }

    threading.Thread(
        target=_run_job, args=(job_id, sources, filters), daemon=True
    ).start()

    return jsonify({"job_id": job_id})


@app.route("/api/jobs/<job_id>")
def api_job_status(job_id):
    """Статус задания."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Задание не найдено"}), 404
    return jsonify(job)


@app.route("/api/results/<job_id>")
def api_results(job_id):
    """Результаты задания с сортировкой."""
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Задание не найдено"}), 404
    if job["status"] != "done":
        return jsonify({"error": "Задание ещё не завершено", "status": job["status"]}), 202

    data     = list(results.get(job_id, []))
    sort_by  = request.args.get("sort_by", "price")
    sort_dir = request.args.get("sort_dir", "asc")

    if sort_by in ("price", "area", "rooms"):
        data.sort(key=lambda x: x.get(sort_by) or 0, reverse=(sort_dir == "desc"))

    src_filter = request.args.get("source")
    if src_filter:
        data = [d for d in data if d.get("source_key") == src_filter]

    return jsonify({"job_id": job_id, "total": len(data), "listings": data})


@app.route("/api/jobs")
def api_jobs():
    """Последние 20 заданий."""
    recent = sorted(jobs.values(), key=lambda j: j["created_at"], reverse=True)[:20]
    return jsonify(recent)


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5050)
