# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes data if possible,
# and also finds (or at least tries to) the start of the sentence in which
# the rating info is contained.
# In particular, a candidate should always have a Tomatometer score available.

import re
import sys
import webbrowser

from dataclasses import dataclass

import googlesearch
import requests

import pywikibot as pwb
from pywikibot.xmlreader import XmlDump

from patterns import *
import scraper


@dataclass
class Candidate:
    title: str
    text: str
    prose: str
    citation: str

    rt_id: str
    rt_data: dict


class Recruiter:
    def __init__(self, xmlfile, patterns):
        self.patterns = patterns
        self.filename = xmlfile

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
                    rt_id = self._extract_rt_id(entry.title, m)
                    if rt_data := self._rt_data(entry.title, rt_id):
                        count += 1

                        # set up attributes
                        title = entry.title
                        text = m.group()
                        prose = self._find_prose(entry.text, m)
                        citation = self._find_citation(entry.text, m)
                        yield Candidate(title, text, prose, citation,
                            rt_id, rt_data)

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


    def _rt_data(self, title, movieid):
        print(title, flush=True)
        data = self._get_data(movieid, title, self._bad_first_try)
        if data:
            return data
        elif rt_data == {}:
            print("Rotten Tomatoes is not currently loading the rating for [[{}]] with id {}. Try again later.".format(entry.title, rt_id), file = sys.stderr)
        return None



    def _get_data(self, movieid, title, func, *args, **kwargs):
        """
        Tries to return the Rotten Tomatoes data for a movie.
        Executes func on a requests.exceptions.HTTPError.
        Func is meant to be a function which returns the desired Rotten Tomatoes data.
        """
        try:
            return scraper.get_rt_rating(rt_url(movieid))
        except requests.exceptions.HTTPError as x:
            print("{}\n".format(x), file=sys.stderr)
            return func(movieid, title, *args, **kwargs)

    def _bad_try(self, movieid, title, msg = None):
        if msg:
            print(msg)
        else:
            print("Problem getting Rotten Tomatoes data for [[{}]] from id {}.".format(title, movieid))


        newid = self._ask_for_id(movieid, title)
        return self._get_data(newid, title, self._bad_try) if newid else None

    def _bad_first_try(self, movieid, title):
        print("Problem getting Rotten Tomatoes data for [[{}]] from id {}.".format(title, movieid),
            file = sys.stderr)
        print("Checking for Wikidata property P1258...", file=sys.stderr)
        if p := self._p1258(title):
            print("Wikidata property P1258 exists with value {}.".format(p), file = sys.stderr)
            msg = 'Problem getting Rotten Tomatoes data for [[{}]] with P1258 value {}.'.format(title, p)
            return self._get_data(p, title, self._bad_try, msg)
        else:
            msg = "Wikidata property P1258 does not exist."
            return self._bad_try(movieid, title, msg)


    def _ask_for_id(self, movieid, title, msg = None):
        """
        Asks for a user decisions regarding the Rotten Tomatoes id for a film
        whose title is the title argument.
        Optional msg argument to be printed at the start of this function.

        Returns:
            if user decides to skip, returns None
            otherwise returns the suggested id or the manually entered id
        """
        if msg:
            print(msg)

        url = googlesearch.lucky(title + " site:rottentomatoes.com/m/")
        suggested_id = url.split('rottentomatoes.com/')[1]

        prompt = """Please select an option:
    1) use suggested id {}
    2) open the suggested id's Rotten Tomato page and [[{}]] in the browser
    3) enter id manually
    4) skip this article
    5) quit the program
Your selection: """.format(suggested_id, title)

        while (user_input := input(prompt)) not in "1345":
            if user_input == '2':
                webbrowser.open(rt_url(movieid))
                webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), title).full_url())
            input("Press Enter when finished in browser.")

            x = lambda t, m: print("Problem getting Rotten Tomatoes data for [[{}]] with id {}. Skipping article.".format(t,m)) or 0
            if user_input == '1':
                return suggested_id
            elif user_input == '3':
                while not (newid := input("Enter id here: ")).startswith('m/'):
                    print('Not a valid id. A valid id begins with "m/".')
                return newid
            elif user_input == '4':
                return print("Skipping article [[{}]].".format(title))
            elif user_input == '5':
                print("Quitting program."); quit()

    @staticmethod
    def _find_start(text, j):
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

        while text[ind] == ' ':
            ind += 1

        return ind

    @staticmethod
    def _find_prose(text, match):
        i = Recruiter._find_start(text, match.start())
        return text[i : match.start('citation')]

    @staticmethod
    def _find_citation(text, match):
        if match.group('citeweb') or match.group('citert') or match.group('rt'):
            return text[match.start('citation') : match.end()]
        else:
            pass


if __name__ == "__main__":
    pass











