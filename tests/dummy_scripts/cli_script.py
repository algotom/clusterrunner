
import argparse
parser = argparse.ArgumentParser()
parser.add_argument('-f', '--file', help='Input file path.', type=str, required=True)
parser.add_argument('--count', default=10, type=int)
parser.add_argument('-v', help='Verbose mode.', action='store_true', default=False)
