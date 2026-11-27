import os

from . import create_app

if __name__ == "__main__":
    app = create_app()
    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000"))
    try:
        from waitress import serve
    except ModuleNotFoundError:
        from werkzeug.serving import run_simple

        run_simple(host, port, app, threaded=True, use_reloader=False)
    else:
        print(f"여행 조율 서버 · http://{host}:{port}", flush=True)
        serve(app, host=host, port=port, threads=8)
