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
from threading import Lock
from dataclasses import dataclass
from collections import namedtuple

import googlesearch
import requests

import pywikibot as pwb
from pywikibot.xmlreader import XmlDump

import scraper
from patterns import *

RTMatch = namedtuple('RTMatch', ['pagetext', 'prose', 'citation', 'rt_id', 'rt_data'])

Candidate = namedtuple('Candidate', ['title', 'matches'])

class NeedsUserInputError(Exception):
    pass

class Recruiter:
    def __init__(self, xmlfile, patterns, get_user_input=True):
        self.patterns = patterns
        self.filename = xmlfile
        self.get_user_input = get_user_input                         

    def candidate_from_entry(self, entry):
        if self.blocked.locked():
            sys.exit()
        title = entry.title
        text = entry.text
        logger.debug(f"candidate_from_entry {title}")

        # Get allowed refnames. Dictionary maps refname to match object of the citation definition
        refnames = dict()
        for m in re.finditer(fr'(?P<citation><ref +name *= *"?(?P<refname>[^>]+?)"? *>((?!<ref).)*{t_alternates}((?!<ref).)*</ref *>)', text, re.DOTALL):
            refnames[m.group('refname')] = m
        # pattern for allowed refnames
        allowed_refname = alternates(re.escape(x) for x in refnames)

        ldref_re = fr'(?P<ldref><ref +name *= *"?(?P<ldrefname>{allowed_refname})"? */>)'
        rtref_re = alternates([citation_re,ldref_re]) if refnames else citation_re

        cand_re8 = fr'{rt_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{score_re}((?!</?ref)[^\n])*?{anyrefs_re}{rtref_re}{anyrefs_re}[.]?'
        cand_re9 = fr'{score_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{rt_re}((?!</?ref)[^\n])*?{anyrefs_re}{rtref_re}{anyrefs_re}[.]?'
        cand_re10 = fr'{t_rtprose}((?!</?ref).)*?{rtref_re}'

        all_matches = list()
        for p in [cand_re8, cand_re9, cand_re10]:
            all_matches.extend(re.finditer(p, text, flags=re.DOTALL))
        
        # different matches may be for the same prose. Only want one.
        prose_set = set()
        # maps a supposed Rotten Tomatoes id rt_id to the value self.rt_data(title, rt_id)
        # So we don't have to scrape the same url twice
        data_dict = dict()

        matches = []
        for m in all_matches:
            prose = self._find_prose(m)
            if prose in prose_set:
                continue
            elif prose_set:
                if self.get_user_input:
                    suggested_id = Recruiter._p1258(title) or Recruiter._get_suggested_id(title)
                    self.multiple_matches_list.append((title, suggested_id))
                return None
            prose_set.add(prose)

            citation, initial_rt_id = self._find_citation_and_id(title, m, refnames)

            # matches.append( RTMatch( text, prose, citation, '', {} ) )
            # break

            try:
                rt_id, rt_data = data_dict.get(initial_rt_id, self._rt_data(title, initial_rt_id))
            except NeedsUserInputError:
                if self.get_user_input:
                    suggested_id = Recruiter._get_suggested_id(title)
                    self.needs_input_list.append((title, text, m, prose, citation, suggested_id))
            else:
                data_dict[initial_rt_id] = (rt_id, rt_data) 
                if rt_data:
                    matches.append( RTMatch( text, prose, citation, rt_id, rt_data ) )


        
        return Candidate(title, matches) if matches else None

    def find_candidates(self):
        """
        Given an XmlDump, yields all pages (as a Candidate) in the dump
        which match at least one pattern in patterns.
        """
        total, count = 0, 0
        xml_entries = XmlDump(self.filename).parse()

        # save pages which need user input for the end
        self.needs_input_list = []
        self.multiple_matches_list = []

        # if we get blocked (status code 403), acquire the lock
        # to let other threads know
        self.blocked = Lock()

        # 15 threads is fine, but don't rerun on the same pages immediately
        # after a run, or the caching may result in sending too many
        # requests too fast, and we'll get blocked.
        with ThreadPoolExecutor(max_workers=15) as x:
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

        for title, text, m, prose, citation, suggested_id in self.needs_input_list:
            while True:
                newid = self._ask_for_id(title, suggested_id)
                if not newid:
                    break
                try:
                    rt_id, rt_data = self._get_data2(newid, title)
                except NeedsUserInputError:
                    print(f"Problem getting Rotten Tomatoes data with id {newid}")
                    continue
                if rt_data:
                    count += 1
                    matches = [RTMatch( text, prose, citation, rt_id, rt_data )]
                    yield Candidate(title, matches)
                break

        logging.debug("multiple_matches_list: %s", self.multiple_matches_list)
        for title, suggested_id in self.multiple_matches_list:
            prompt = f"""Multiple matches found in [[{title}]].\nPlease select an option.
    1) open {rt_url(suggested_id)} and [[{title}]] in the browser for manual editing
    2) skip this article
    3) quit the program
Your selection: """
            while print() or (user_input := input(prompt)) not in ['1', '2', '3']:
                print("Not a valid selection.")

            if user_input == '1':
                webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), title).full_url())
                webbrowser.open(rt_url(suggested_id))
            elif user_input == '2':
                continue
            elif user_input == '3':
                print("Quitting program."); sys.exit()



        logger.info("Found %s candidates out of %s pages", count, total)


    def _rt_data(self, title, movieid):
        """
        Tries to return the Rotten Tomatoes data for a movie.
        Raises NeedsUserInputError if it is determined that the
        user will need to be asked for a Rotten Tomatoes id.

        Two possible return values if NeedsUserInputError is not raised.
        1. id, data. The rating data we want.
        2. id, empty dict. Which happens when the rating data exists but
        Rotten Tomatoes is having trouble loading the rating data for a movie.
        """
        if self.blocked.locked():
            sys.exit()

        logger.info("Processing potential candidate [[%s]]", title)

        try:
            return movieid, scraper.get_rt_rating(rt_url(movieid))
        except requests.exceptions.HTTPError as x:
            if x.response.status_code == 403:
                self.blocked.acquire(blocking=False)
                logger.exception("Probably blocked by rottentomatoes.com. Exiting thread")
                sys.exit()
            elif x.response.status_code == 404:
                logger.exception("404 Client Error")
            elif x.response.status_code == 500:
                logger.exception("500 Server Error")
            else:
                logger.exception("An unknown HTTPError occured for [[%s]] with id %s", title, movieid)
                raise
        except requests.exceptions.TooManyRedirects as x:
            logger.exception("Too many redirects for [[%s]] with id %s", title, movieid)

        logger.info("Problem getting Rotten Tomatoes data for [[%s]] with id %s. Trying Wikidata property P1258...", title, movieid)
        if p := Recruiter._p1258(title):
            logger.info("Found Wikidata property P1258 for [[%s]]: %s", title, p)

            if p == movieid: # in case it's the same and we already know it fails
                logger.info(f'Problem getting Rotten Tomatoes data for [[{title}]] with P1258 value {p}')
                raise NeedsUserInputError

            try:
                return p, scraper.get_rt_rating(rt_url(p))
            except requests.exceptions.HTTPError as x:
                if x.response.status_code == 403:
                    self.blocked.acquire(blocking=False)
                    logger.exception("Probably blocked by rottentomatoes.com. Exiting thread")
                    sys.exit()
                elif x.response.status_code == 404:
                    logger.exception("404 Client Error")
                elif x.response.status_code == 500:
                    logger.exception("500 Server Error")
                else:
                    logger.exception("An unknown HTTPError occured for [[%s]] with id %s", title, p)
                    raise
            except requests.exceptions.TooManyRedirects as x:
                logger.exception("Too many redirects for [[%s]] with id %s", title, p)

            logger.info(f'Problem getting Rotten Tomatoes data for [[{title}]] with P1258 value {p}')
        else:
            logger.info(f"Wikidata property P1258 does not exist for [[{title}]]")

        raise NeedsUserInputError

    def _ask_for_id(self, title, suggested_id):
        """
        Asks for a user decision regarding the Rotten Tomatoes id for a film.

        Returns:
            if user decides to skip, returns None
            otherwise returns the suggested id or a manually entered id
        """
        prompt = f"""Please select an option for [[{title}]]:
    1) use suggested id {suggested_id}
    2) open {rt_url(suggested_id)} and [[{title}]] in the browser
    3) enter id manually
    4) skip this article
    5) quit the program
Your selection: """

        while (user_input := input(prompt)) not in ['1', '3', '4', '5']:
            if user_input == '2':
                webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), title).full_url())
                webbrowser.open(rt_url(suggested_id))
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
            logger.info("Skipping article [[%s]]", title)
        elif user_input == '5':
            print("Quitting program."); sys.exit()

    # ===========================================================================================

    @staticmethod
    def _find_prose(match):
        """
        This function is supposed to return the prose part of the match.
        It tries find the beginning of
        the sentence containing the Rotten Tomatoes rating info.

        NOTE: There are edge cases where the start position found
        by this function
        is in fact NOT the start of the desired sentence.
        For example, if the movie title is 'Mr. Bobby' and it isn't italicized
        in the Wikitext, then this function might identify the start at 'B'.
        
        Args:
            match: match object which identified this potential candidate
        """
        text = match.string
        italics = False
        for i in range(match.start() - 1, -1, -1):
            c = text[i]
            if c in "\n>" or (c == "." and not italics and text[i+1] == ' '):
                ind = i + 1
                break
            elif c == "'" == text[i + 1]:
                italics = not italics

        while text[ind] == ' ':
            ind += 1

        return text[ ind : match.end() ]



    @staticmethod
    def _find_citation(match):
        text = match.string
        # list-defined reference case
        if 'ldrefname' in match.groupdict() and (ldrefname := match.group('ldrefname')):
            ldrefname = re.escape(ldrefname)
            ldrefname = fr'({ldrefname}|"{ldrefname}")'

            #p = fr"<ref +name *= *{ldrefname} *>[^<>]*?{t_alternates}[^<>]*?</ref *>"

            #p = fr"<ref +name *= *{ldrefname} *>.*?{t_alternates}.*?</ref *>"

            p = fr"<ref +name *= *{ldrefname} *>((?!</ref).)*?{t_alternates}((?!</ref).)*?</ref *>"

            m = re.search(p, text, flags=re.DOTALL)

            # Technically it's possible that we didn't find the definition of the
            # reference with name ldrefname, e.g. no proper citation.
            # In this case we return None
            return m.group() if m else None
        # inline reference case
        else:
            return text[match.start('citation') : match.end('citation')]

    @staticmethod
    def _find_citation_and_id(title, m, refnames):
        groupdict = m.groupdict()
        if ldrefname := groupdict.get('ldrefname'):
            citation = refnames[ldrefname].group()
            groupdict = refnames[ldrefname].groupdict()
        else:
            citation = m.group('citation')


        if rt_id := groupdict.get('rt_id'):
            return citation, rt_id
        elif citert := groupdict.get('citert'):
            d = parse_template(citert)[1]
            return (citation, "m/" + d['id'])
        elif rt := groupdict.get('rt'):
            d = parse_template(rt)[1]
            if 1 in d.keys() or 'id' in d.keys():
                key = 1 if 1 in d.keys() else 'id'
                return (citation, ["m/",""][d[key].startswith("m/")] + d[key])
            elif p := Recruiter._p1258(title):
                return (citation, p)

        raise ValueError(f'Problem getting citation and id for a match in [[{title}]]')

    @staticmethod
    def _p1258(title):
        page = pwb.Page(pwb.Site('en','wikipedia'), title)
        item = pwb.ItemPage.fromPage(page)
        item.get()
        if 'P1258' in item.claims:
            return item.claims['P1258'][0].getTarget()
        return None

    @staticmethod
    def _get_suggested_id(title):
        url = googlesearch.lucky(title + " site:rottentomatoes.com/m/")
        suggested_id = url.split('rottentomatoes.com/m/')[1]
        # in case it's like titanic/reviews
        suggested_id = 'm/' + suggested_id.split('/')[0]
        return suggested_id

if __name__ == "__main__":
    pass



