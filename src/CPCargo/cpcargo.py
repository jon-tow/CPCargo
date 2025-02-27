import signal, functools, logging, sys
from watchdog.observers import Observer
from watchdog.observers.api import ObservedWatch
from CPCargo.handler import CheckpointHandler
from multiprocessing import Queue, Process
import queue, logging, time, os
from CPCargo.uploaders import S3Uploader

logging.basicConfig(
    format=
    '%(asctime)s.%(msecs)03d %(name)s %(filename)s:%(funcName)s:%(lineno)d %(message)s',
    datefmt='%Y-%m-%d,%H:%M:%S',
    level=logging.INFO)
logger = logging.getLogger("CPCargo")


class Watcher():
  _observer: Observer
  _watch: ObservedWatch

  def __init__(self,
               src_dir: str,
               dst_url: str,
               region: str = "us-east-1",
               file_regex: str = ".*",
               recursive: bool = False) -> None:
    self._dst = dst_url
    self._src_path = src_dir
    self._file_re = file_regex
    self._recursive = recursive
    self._region = region
    self._observer = None
    self._uploader = S3Uploader(region=region,
                                src_prefix=src_dir,
                                dst_url=dst_url,
                                pool_size=0)
    self._handler = CheckpointHandler(uploader=self._uploader,
                                      file_regex=self._file_re,
                                      recursive=self._recursive)
    self._watch = None

  def start(self):
    logger.info("Watcher start")
    if not self._observer:
      self._observer = Observer()
      self._watch = self._observer.schedule(self._handler, self._src_path,
                                            self._recursive)
    if not self._observer.is_alive():
      self._observer.start()

  def stop(self, timeout=20):
    logger.info("Watcher stop")
    if self._observer:
      self._observer.unschedule_all()
      if self._observer.is_alive():
        self._observer.stop()
      self._observer = None


def watcher(src: str,
            dst: str,
            file_re: str,
            region: str,
            terminate_queue: Queue,
            recursive: bool,
            timeout: int = 100):
  agent = Watcher(src_dir=src,
                  dst_url=dst,
                  region=region,
                  file_regex=file_re,
                  recursive=recursive)
  logger.info("Starting watcher")
  agent.start()
  try:
    while True:
      time.sleep(2)
      try:
        end = terminate_queue.get_nowait()
        if end:
          break
      except queue.Empty as e:
        pass
  except KeyboardInterrupt:
    pass
  finally:
    logger.info("Stopping watcher")
    agent.stop(timeout)


class CheckpointCargo():

  def __init__(self,
               src_dir: str,
               dst_url: str,
               region: str,
               file_regex: str = ".*",
               recursive: bool = False) -> None:
    self._queue = Queue()
    self._src = os.path.abspath(src_dir)
    self._process = Process(
        target=watcher,
        args=[self._src, dst_url, file_regex, region, self._queue, recursive])

  def start(self):
    logger.info("Starting Cargo on {path}".format(path=self._src))
    if self._process.exitcode:
      raise RuntimeError("Process already exited!")
    self._process.start()

  def stop(self, timeout=100):
    logger.info("Stopping Cargo")
    self._queue.put_nowait(True)
    self._process.join(timeout)
    logger.info(
        "Watcher subprocess returned {ret}".format(ret=self._process.exitcode))
