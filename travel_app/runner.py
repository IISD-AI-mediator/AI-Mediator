import logging
import threading
from concurrent.futures import ThreadPoolExecutor


class Runner:
    """The persisted due index remains authoritative across restarts and workers."""

    def __init__(self, store, graph):
        self.store, self.graph = store, graph
        self.wake = threading.Event()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, name="travel-scheduler", daemon=True)

    def run(self):
        active = {}
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="travel-room") as pool:
            while not self.stop.is_set():
                try:
                    for invite, future in list(active.items()):
                        if future.done():
                            del active[invite]
                            future.result()
                    for invite in self.store.due():
                        if len(active) >= 2:
                            break
                        if invite not in active:
                            active[invite] = pool.submit(self.graph.invoke, {"invite": invite}, {"recursion_limit": 240})
                except Exception:
                    logging.getLogger(__name__).exception("Travel scheduler iteration failed")
                self.wake.wait(0.6)
                self.wake.clear()

    def close(self):
        self.stop.set()
        self.wake.set()
