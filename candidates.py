# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes data if possible,
# and also finds (or at least tries to) the start of the sentence in which
# the rating info is contained.
# In particular, a candidate should always have a Tomatometer score available.

import re
import sys
import webbrowser

import googlesearch
import requests

import pywikibot as pwb
from pywikibot.xmlreader import XmlDump

from patterns import *
import scraper




class Candidate:
    """
    Holds the info we'll need for a candidate page to be edited.
    """

    def __init__(self, entry, match, rt_id, rt_data):
        self.title = entry.title
        self.id = entry.id
        self.score = match.group('score')
        # citation text
        self.citation = self._find_citation(entry.text, match)
        # prose text
        self.prose = self._find_prose(entry.text, match)
        self.rt_id = rt_id
        self.rt_data = rt_data


    def _find_start(self, text, j):
        """
        This function is supposed to find the index of the beginning of
        the sentence containing the Rotten Tomatoes rating info.

        NOTE: There are edge cases where the index returned by this function
        is in fact NOT the start of the desired sentence (see suspicious_start).
        In these cases the bot operator will be asked for input.

        Args:
            text: the text of the page
            j: the start index of the re.Match object
        """
        italics = False
        for i in range(j - 1, -1, -1):
            c = text[i]
            if c in "\n>":
                ind = i + 1
                break
            elif c == "." and not italics:
                ind = i + 1
                break
            elif c == "'" == text[i + 1]:
                italics = not italics

        ind += (text[ind] == ' ')

        return ind


    def _find_citation(self, text, match):
        pass

    def _find_prose(self, text, match):
        i = self._find_start(text,match.start())
        return text[i : match.start('citation')]


class Recruiter:
    def __init__(self, xmlfile, patterns):
        self.filename = xmlfile
        self.patterns = patterns

    def find_candidates(self):
        """
        Given an XmlDump, yields all pages (as a Candidate) in the dump
        which match at least one pattern in patterns.
        """
        total, count = 0, 0
        for entry in XmlDump(self.filename).parse():
            total += 1
            for p in self.patterns:
                if m := re.search(p, entry.text):
                    count += 1
                    rt_id = self._extract_rt_id(entry.title, m)
                    rt_data = self._rt_data(entry.title, rt_id)
                    if rt_data:
                        yield Candidate(entry, m, rt_id, rt_data)
                    elif rt_data is None:
                        print("Tomatometer not yet available for id {}.".format(rt_id),
                            file=sys.stderr)
                        rt_data = self._ask_for_option(entry.title)
                        if rt_data:
                            yield Candidate(entry, m, rt_id, rt_data)
                    break

        print("CANDIDATES / TOTAL = {} / {}".format(count, total))


    def _p1258(self, title):
        page = pwb.Page(pwb.Site('en','wikipedia'), title)
        item = pwb.ItemPage.fromPage(page)
        item.get()
        if 'P1258' in item.claims:
            return item.claims['P1258'][0].getTarget()
        return None


    def _extract_rt_id(self, title, match):
        """
        Given the re.Match object which has identified a candidate, extracts the movieid.
        """

        # Cite web template case
        if match.group('citeweb'):
            return match.group('rt_id')

        # Cite Rotten Tomatoes template case
        if match.group('citert'):
            d = parse_template(match.group('citert'))[1]
            return "m/" + d['id']

        # Rotten Tomatoes template case 
        if match.group('rt'):
            d = parse_template(match.group('rt'))[1]
            if 'id' in d.keys():
                return ("" if d['id'].startswith('m/') else "m/") + d['id'] 
            if 1 in d.keys():
                return ("" if d[1].startswith('m/') else "m/") + d[1]

            # Check for Wikidata property P1258
            if p := self._p1258(title):
                return p

        raise ValueError("Could not find the Rotten Tomatoes ID for [[{}]].".format(self.title))

    def _rt_data_try(self, title, movieid, func):
        """
        Tries to return the RT data from rt_url(movieid),
        and executes func on a requests.exceptions.HTTPError
        """
        try:
            return scraper.get_rt_rating(rt_url(movieid))
        except requests.exceptions.HTTPError as x:
            print("{}\n".format(x), file=sys.stderr)
            return func(title, movieid)

    def _rt_data_bad_first_try(self, title, movieid):
        print("Problem getting Rotten Tomatoes data for [[{}]] with id {}.".format(title, movieid),
            file = sys.stderr)
        print("Checking for Wikidata property P1258...", file=sys.stderr)
        if p := self._p1258():
            print("Wikidata property P1258 exists: {}.".format(p),
                file = sys.stderr)
            return self._rt_data_try(title, p, self._rt_data_bad_p1258_try)
        else:
            print("Wikidata property P1258 does not exist.", file=sys.stderr)
            return self._ask_for_option(title)

    def _rt_data_bad_p1258_try(self, title, movieid):
        print("Problem getting Rotten Tomatoes data for [[{}]] with with P1258 {}.".format(title, movieid),
            file=sys.stderr)
        return self._ask_for_option(title)

    def _ask_for_option(self, title):
        url = googlesearch.lucky(title + " site:rottentomatoes.com/m/")
        movieid = url.split('rottentomatoes.com/')[1]
        prompt = """Please select an option:
    1) use suggested id {}
    2) open the suggested RT page and [[{}]] in the browser
    3) enter id manually
    4) skip this article
    5) quit the program
Your selection: """.format(movieid, title)
        while (user_input := input(prompt)) not in "134":
            if user_input == '2':
                webbrowser.open(rt_url(movieid))
            webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), title).full_url())
            input("Press Enter when finished in browser.")

            x = lambda t, m: print("Problem getting Rotten Tomatoes data for [[{}]] with id {}. Skipping article.".format(t,m)) or 0
            if user_input == '1':
                return self._rt_data_try(title, movieid, x)
            elif user_input == '3':
                newid = input("Enter id here: ")
                return self._rt_data_try(title, newid, x)
            elif user_input == '4':
                return print("Skipping article [[{}]].".format(title)) or 0
            elif user_input == '5':
                print("Quitting program."); quit()

    def _rt_data(self, title, movieid):
        print(title, flush=True)
        return self._rt_data_try(title, movieid, self._rt_data_bad_first_try)



if __name__ == "__main__":
    pass











