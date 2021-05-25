# This module is takes Candidates from the candidates.py module and
# determines whether or not it should be edited.
# If so, it produces an Edit object which
# contains the relevant page, the old text to be replaced, and the replacement text.

import re

import scraper
from patterns import *


def find_start(text, j):
	st = {'\n', '.', '>'}
	ind = next((i for i in range(j-1, -1, -1) if text[i] in st), None)
	if text[ind] == '\n':
		return ind + 1
	else:
		return ind + 2




def check_for_update(text):
	t = scraper.get_rt_rating()


if __name__ == "__main__":
	print(find_start("df. dfasdfasdf", 5))