#!/usr/bin/env python3

import quilt3
from quilt3 import Package
import uuid

import time

def humanize_float(num): return "{0:,.2f}".format(num)

class Timer:
    def __init__(self, name):
        self.name = name
        self.t1 = None
        self.t2 = None

    def start(self):
        print(f'Timer "{self.name}" starting!')
        self.t1 = time.time()

        return self

    def stop(self):
        self.t2 = time.time()
        print(f'Timer "{self.name}" took {humanize_float(self.t2-self.t1)} seconds')


def setup():
    pkg = Package()
    # data_dir = "/home/ubuntu/coco/data/train2017/"
    data_dir = "/home/ubuntu/coco/data/val2017/"
    t = Timer(f"pkg.set_dir({data_dir})").start()
    pkg.set_dir("data", data_dir)
    t.stop()
    return pkg

def perf_test():
    pkg = setup()
    thash = Timer("hash files").start()
    pkg._fix_sha256()
    thash.stop()
    tpush = Timer("materialize files").start()
    pkg._materialize(dest_url=f"s3://quilt-ml-data/tst/{uuid.uuid4()}/")
    tpush.stop()

if __name__ == '__main__':
    perf_test()

    # Original hash with val2017 takes 11 seconds to hash (7e965f38f035bba7046f86cc663be0ca30246b31)
    # Lock free took 4 seconds (7e965f38f035bba7046f86cc663be0ca30246b31)

    # Original hash with train2017 takes 282 seconds to hash (7e965f38f035bba7046f86cc663be0ca30246b31)
    # Lock free took 96 seconds (7e965f38f035bba7046f86cc663be0ca30246b31)
    # Lock free, multiprocess took 7 seconds (445145cb434e1a9eb69ed025001d871445842342)

    # Original push with val2017 takes 130 seconds
    # Refactored push with val2017 takes 58 seconds (20 pool workers)
    # Refactored push with val2017 takes 36 seconds (40 pool workers)
    # Refactored push with val2017 takes 24 seconds (40 pool workers, single s3_client creation per process)

    # Assuming similar improvements, coco should go from
    # 6:27 to hash and 72:15 (4335seconds) to push
    # to :10 to hash and 14:00 to push

    # Actual: 11secs to hash, 741sec to push (12:21)