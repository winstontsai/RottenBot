# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes data if possible,
# and also finds (or at least tries to) the start of the sentence in which
# the rating info is contained.
# In particular, a candidate should always have a Tomatometer score available.

import re
import sys
import webbrowser
import logging
logger = logging.getLogger(__name__)

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
                    if (citation := Recruiter._find_citation(entry.text, m)) is None:
                        continue
                    rt_id = Recruiter._find_id(citation)
                    if rt_data := self._rt_data(entry.title, rt_id):
                        count += 1
                        yield Candidate(
                            title=entry.title,
                            text=m.group(),
                            prose=self._find_prose(entry.text, m),
                            citation=citation,
                            rt_id=rt_id,
                            rt_data=rt_data)
                        break

        logger.info("Found {} candidates out of {} pages.".format(count, total))

    @staticmethod
    def _p1258(title):
        page = pwb.Page(pwb.Site('en','wikipedia'), title)
        item = pwb.ItemPage.fromPage(page)
        item.get()
        if 'P1258' in item.claims:
            return item.claims['P1258'][0].getTarget()
        return None


    @staticmethod
    def _find_citation(text, match):
        if match.group('citeweb') or match.group('citert') or match.group('rt'):
            return text[match.start('citation') : match.end()]
        else: # list-defined reference case
            refname = match.group('ldrefname')
            p = "<ref name ?= ?{} ?>{}".format(refname, alternates([t_citeweb, t_citert, t_rt]))
            if m := re.search(p, text):
                return m.group()
            else:
                # Technically it's possible that we didn't find the definition of the
                # reference with name refname, e.g. no proper citation.
                return None

    @staticmethod
    def _find_id(citation):
        answer = None

        # Cite web template case
        if m := re.search(t_citeweb, citation):
            answer = m.group('rt_id')

        # Cite Rotten Tomatoes template case
        elif m := re.search(t_citert, citation):
            d = parse_template(m.group('citert'))[1]
            answer = "m/" + d['id']

        # Rotten Tomatoes template case 
        elif m := re.search(t_rt, citation):
            d = parse_template(m.group('rt'))[1]
            if 1 in d.keys() or 'id' in d.keys():
                key = ['id', 1][1 in d.keys()]
                answer = ["m/",""][d[key].startswith('m/')] + d[key]

            # Check for Wikidata property P1258
            elif p := Recruiter._p1258(title):
                answer = p
        
        logger.debug('Found id {} from the citation "{}"'.format(answer, citation))
        if answer is None:
            logger.error("Could not find a Rotten Tomatoes ID from the following citation: {}".format(citation))
        return answer


    def _rt_data(self, title, movieid):
        """
        Three possible return values.
        1. The rating data we want.
        2. None. Which means there is no rating data, or the user opted to skip.
        3. Empty dict, which happens when the rating data exists but
        Rotten Tomatoes is having trouble loading the rating data for a movie.
        """
        logger.info("Obtaining data for [[{}]]...".format(title))
        data = self._get_data(movieid, title, self._bad_first_try)
        return data



    def _get_data(self, movieid, title, func, *args, **kwargs):
        """
        Tries to return the Rotten Tomatoes data for a movie.
        Executes func on a requests.exceptions.HTTPError.
        Func is meant to be a function which returns the desired Rotten Tomatoes data.
        """
        try:
            return scraper.get_rt_rating(rt_url(movieid))
        except requests.exceptions.HTTPError as x:
            logger.info("{}".format(x))
            return func(movieid, title, *args, **kwargs)

    def _bad_first_try(self, movieid, title):
        logger.info("Problem getting Rotten Tomatoes data for [[{}]] from id {} on first try.".format(title, movieid))
        logger.info("Checking for Wikidata property P1258...")
        if p := Recruiter._p1258(title):
            logger.info("Wikidata property P1258 exists with value {}.".format(p))
            msg = 'Problem getting Rotten Tomatoes data for [[{}]] with P1258 value {}.'.format(title, p)
            return self._get_data(p, title, self._bad_try, msg)
        else:
            msg = "Wikidata property P1258 does not exist."
            return self._bad_try(movieid, title, msg)

    def _bad_try(self, movieid, title, msg = None):
        if msg:
            logger.info(msg)
        else:
            logger.info("Problem getting Rotten Tomatoes data for [[{}]] from id {}.".format(title, movieid))

        newid = self._ask_for_id(title)
        return self._get_data(newid, title, self._bad_try) if newid else None


    def _ask_for_id(self, title):
        """
        Asks for a user decisions regarding the Rotten Tomatoes id for a film
        whose title is the title argument.

        Returns:
            if user decides to skip, returns None
            otherwise returns the suggested id or the manually entered id
        """

        url = googlesearch.lucky(title + " site:rottentomatoes.com/m/")
        suggested_id = url.split('rottentomatoes.com/')[1]

        prompt = """Please select an option for [[{}]]:
    1) use suggested id {}
    2) open the suggested id's Rotten Tomato page and [[{}]] in the browser
    3) enter id manually
    4) skip this article
    5) quit the program
Your selection: """.format(title, suggested_id, title)

        while (user_input := input(prompt)) not in "1345":
            if user_input == '2':
                webbrowser.open(rt_url(suggested_id))
                webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), title).full_url())
            input("Press Enter when finished in browser.")

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




if __name__ == "__main__":
    pass











