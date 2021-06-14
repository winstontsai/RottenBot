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

from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue
from dataclasses import dataclass

import googlesearch
import requests

import pywikibot as pwb
from pywikibot.xmlreader import XmlDump

import scraper
from patterns import *



@dataclass
class Candidate:
    title: str
    text: str
    prose: str
    citation: str

    rt_id: str
    rt_data: dict


class NeedsUserInputError(Exception):
    pass

class BlockedError(Exception):
    pass

class Recruiter:
    def __init__(self, xmlfile, patterns, get_user_input=True):
        self.patterns = patterns
        self.filename = xmlfile
        self.get_user_input = get_user_input

    def candidate_from_entry(self, entry):
        if not self.blocked.empty():
            sys.exit()

        logging.debug("candidate_from_entry {}".format(entry.title))

        for p in self.patterns:
            if m := re.search(p, entry.text):
                if not (citation := Recruiter._find_citation(entry.text, m)):
                    logging.info("No citation found for [[{}]]".format(entry.title))
                    continue
                rt_id = Recruiter._find_id(citation)
                try:
                    rt_id, rt_data = self._rt_data(entry.title, rt_id)
                except NeedsUserInputError:
                    if self.get_user_input:
                        self.needs_input_list.append((entry, m, citation, rt_id))
                else:
                    if rt_data:
                        return Candidate(
                            title=entry.title,
                            text=m.group(),
                            prose=self._find_prose(entry.text, m),
                            citation=citation,
                            rt_id=rt_id,
                            rt_data=rt_data)

        return None # not a candidate

    def find_candidates(self):
        """
        Given an XmlDump, yields all pages (as a Candidate) in the dump
        which match at least one pattern in patterns.
        """
        total, count = 0, 0
        xml_entries = XmlDump(self.filename).parse()

        # save pages which need user input for the end
        self.needs_input_list = []

        # if we get blocked (status code 403), add something to this queue
        # if Queue is empty, then not blocked.
        # if Queue is not empty, then we got blocked
        self.blocked = Queue()

        # 20 threads is fine, but don't rerun on the same pages immediately
        # after a run, or the caching may result in sending too many
        # requests too fast, and we'll get blocked.
        with ThreadPoolExecutor(max_workers=20) as x:
            futures = (x.submit(self.candidate_from_entry, entry) for entry in xml_entries)
            for future in as_completed(futures, timeout=None):
                total += 1
                try:
                    cand = future.result()
                except SystemExit:
                    x.shutdown(wait=True, cancel_futures=True)
                    logger.error("Exiting program.")
                    sys.exit()
                else:
                    if cand:
                        count += 1
                        yield cand

        for entry, m, citation, rt_id in self.needs_input_list:
            rt_id, rt_data = self._bad_try(rt_id, entry.title, user_input_mode=True)
            if rt_data:
                count += 1
                yield Candidate(
                    title=entry.title,
                    text=m.group(),
                    prose=self._find_prose(entry.text, m),
                    citation=citation,
                    rt_id=rt_id,
                    rt_data=rt_data)


        logger.info("Found {} candidates out of {} pages".format(count, total))


    def _rt_data(self, title, movieid):
        """
        Three possible return values.
        1. id, data. The rating data we want.
        2. _ , none. Which means there is no rating data, or the user opted to skip.
        3. id, empty dict. Which happens when the rating data exists but
        Rotten Tomatoes is having trouble loading the rating data for a movie.
        """
        if not self.blocked.empty():
            sys.exit()

        logger.info("Processing potential candidate [[{}]]".format(title))
        return self._get_data(movieid, title, self._bad_first_try)



    def _get_data(self, movieid, title, func, *args, **kwargs):
        """
        Tries to return the Rotten Tomatoes data for a movie.
        Executes func if there is a requests.exceptions.HTTPError.
        Func is meant to be a function which returns the desired Rotten Tomatoes data
        in a tuple (id, data).
        """
        if not self.blocked.empty():
            raise sys.exit()

        try:
            return movieid, scraper.get_rt_rating(rt_url(movieid))
        except requests.exceptions.HTTPError as x:
            if x.response.status_code == 403:
                self.blocked.put("blocked")
                logger.exception("Probably blocked by rottentomatoes.com. Exiting thread")
                sys.exit()
            elif x.response.status_code == 404:
                logger.exception("404 Client Error")
            elif x.response.status_code == 500:
                logger.exception("500 Server Error")
            else:
                logger.exception("An unknown HTTPError occured for [[{}]] with id {}".format(title, movieid))
                raise
            return func(movieid, title, *args, **kwargs)
        except requests.exceptions.TooManyRedirects as x:
            logger.exception("Too many redirects for [[{}]] with id {}".format(title, movieid))
            return func(movieid, title, *args, **kwargs)

    def _bad_first_try(self, movieid, title):
        logger.info("Problem getting Rotten Tomatoes data for [[{}]] from id {}. Checking for Wikidata property P1258...".format(title, movieid))
        if p := Recruiter._p1258(title):
            logger.debug("Found Wikidata property P1258 for [[{}]]".format(title, p))
            msg = 'Problem getting Rotten Tomatoes data for [[{}]] with P1258 value {}'.format(title, p)
            if p == movieid:
                return self._bad_try(movieid, title, msg)
            return self._get_data(p, title, self._bad_try, msg)
        else:
            msg = "Wikidata property P1258 does not exist for [[{}]]".format(title)
            return self._bad_try(movieid, title, msg)

    def _bad_try(self, movieid, title, msg = None, user_input_mode = False):
        if user_input_mode:
            if newid := self._ask_for_id(title):
                return self._get_data(newid, title, self._bad_try, user_input_mode=True)
            return None, None
        else:
            if msg:
                logger.info(msg)
            else:
                logger.info("Problem getting Rotten Tomatoes data for [[{}]] from id {}".format(title, movieid))
            logger.debug("[[{}]] will need user's input".format(title))
            raise NeedsUserInputError


    def _ask_for_id(self, title):
        """
        Asks for a user decision regarding the Rotten Tomatoes id for a film.

        Returns:
            if user decides to skip, returns None
            otherwise returns the suggested id or a manually entered id
        """

        url = googlesearch.lucky(title + " site:rottentomatoes.com/m/")
        suggested_id = url.split('rottentomatoes.com/m/')[1]
        # in case it's like m/moviename/reviews
        suggested_id = 'm/' + suggested_id.split('/')[0]

        prompt = """Please select an option for [[{}]]:
    1) use suggested id {}
    2) open the suggested id's Rotten Tomato page and [[{}]] in the browser
    3) enter id manually
    4) skip this article
    5) quit the program
Your selection: """.format(title, suggested_id, title)

        while (user_input := input(prompt)) not in ['1', '3', '4', '5']:
            if user_input == '2':
                webbrowser.open(rt_url(suggested_id))
                webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), title).full_url())
                input("Press Enter when finished in browser.")
            else:
                print("Not a valid selection.")

        if user_input == '1':
            return suggested_id
        elif user_input == '3':
            while not (newid := input("Enter id here: ")).startswith('m/'):
                print('Not a valid id. A valid id begins with "m/".')
            return newid
        elif user_input == '4':
            return None
            # return print("Skipping article [[{}]].".format(title))
        elif user_input == '5':
            print("Quitting program."); sys.exit()

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
            j: the start index, beginning of sentence should come before
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
        
        if answer is None:
            logger.error("Could not find a Rotten Tomatoes ID from the following citation: {}".format(citation))
        else:
            logger.debug('Found id {} from the citation "{}"'.format(answer, citation))

        return answer

    @staticmethod
    def _p1258(title):
        page = pwb.Page(pwb.Site('en','wikipedia'), title)
        item = pwb.ItemPage.fromPage(page)
        item.get()
        if 'P1258' in item.claims:
            return item.claims['P1258'][0].getTarget()
        return None

if __name__ == "__main__":
    pass











