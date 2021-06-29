# This module does some preprocessing.
# It identifies "candidate" pages that contain Rotten Tomatoes rating info,
# finds the corresponding Rotten Tomatoes data if possible,
# and also finds (or at least tries to) the start of the sentence in which
# the rating info is contained.
# In particular, a candidate should always have a Tomatometer score available.

import re
import sys
import webbrowser
import io
import os.path
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


class NeedsUserInputError(Exception):
    pass

Entry = namedtuple('Entry', ["title", "text"])

@dataclass
class Reference:
    reftext: str
    refname: str = None
    ld: bool = False

@dataclass
class Candidate:
    title: str
    pagetext: str
    span: tuple[int, int, int]
    prose: str
    ref: Reference
    rt_id: str = ''
    rt_data: dict = None

class Recruiter:
    def __init__(self, xmlfile):
        self.filename = xmlfile                       

    # entry just needs .title and .text attributes for the page we are interested in
    def candidate_from_entry(self, entry, get_all = False, get_user_input = True):
        """
        When get_all is False, the behavior is as follows:
        If multiple matches are found, the title is appended to
        self.multiple_matches_list and None is returned.
        If a single candidate is found with valid rt_data, it is returned.
        If a single candidate is found without valid rt_data, 
        """
        if self.blocked.locked():
            sys.exit()

        print(f"Processing [[{entry.title}]]")

        title = entry.title
        text = entry.text

        # Get allowed refnames. Dictionary maps refname to match object of the citation definition
        refnames = dict()
        for m in re.finditer(fr'(?P<citation><ref +name *= *"?(?P<refname>[^>]+?)"? *>((?!<ref).)*{t_alternates}((?!<ref).)*</ref *>)', text, re.DOTALL):
            refnames[m.group('refname')] = m
        # pattern for allowed refnames
        allowed_refname = alternates(map(re.escape, refnames)) 

        ldref_re = fr'(?P<ldref><ref +name *= *"?(?P<ldrefname>{allowed_refname})"? */>)'
        rtref_re = alternates([citation_re,ldref_re]) if refnames else citation_re

        cand_re8 = fr'{rt_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{score_re}((?!</?ref)[^\n])*?{anyrefs_re}{rtref_re}{anyrefs_re}[.]?'
        cand_re9 = fr'{score_re}(?!((?!<!--)[^\n])*-->)((?!</?ref)[^\n])*?{rt_re}((?!</?ref)[^\n])*?{anyrefs_re}{rtref_re}{anyrefs_re}[.]?'
        cand_re10 = fr'{t_rtprose}((?!</?ref).)*?{rtref_re}'

        all_matches = []
        for p in [cand_re8, cand_re9, cand_re10]:
            all_matches.extend(re.finditer(p, text, re.DOTALL))
        
        cand_list = []
        prose_set = set()      # different matches may be for the same prose
        
        for m in all_matches:
            span, prose = self._find_span_and_prose(m)
            if prose in prose_set:
                continue
            prose_set.add(prose)

            if cand_list and not get_all:
                if get_user_input:
                    self.multiple_matches_list.append(title)
                return None

            ref, initial_rt_id = self._find_citation_and_id(title, m, refnames)
            cand = Candidate(
                    title = title,
                    pagetext = text,
                    span = span,
                    prose = prose,
                    ref = ref,)
            try:
                rt_id, rt_data = self._rt_data(title, initial_rt_id,
                    use_p1258 = not get_all)
            except NeedsUserInputError:
                cand.suggested_id = Recruiter.suggested_id(title)
            else:
                #if rt_data:
                cand.rt_id, cand.rt_data = rt_id, rt_data

            cand_list.append(cand)

        if get_all:
            return [x for x in cand_list if x.rt_data]
        elif cand_list:
            cand = cand_list[0]
            if cand.rt_data:
                return cand
            elif get_user_input and hasattr(cand, 'suggested_id'):
                self.needs_input_list.append(cand)                
                

    def find_candidates(self, get_user_input = True):
        """
        Given an XmlDump, yields all pages (as a Candidate) in the dump
        which match at least one pattern in patterns.
        """
        # if we get blocked (status code 403), acquire the lock
        # to let other threads know
        self.blocked = Lock()

        total, count = 0, 0
        xml_entries = XmlDump(self.filename).parse()

        # Save pages which need user input for the end
        # this list contains the candidates which need user input
        # to get rt_id and rt_data
        self.needs_input_list = []
        # this list contains the titles of pages with multiple matches
        self.multiple_matches_list = []

        # 15 threads is fine, but don't rerun on the same pages immediately
        # after a run, or the caching may result in sending too many
        # requests too fast, and we'll get blocked.
        with ThreadPoolExecutor(max_workers=15) as x:
            futures = (x.submit(self.candidate_from_entry,
                    entry, get_user_input=get_user_input) for entry in xml_entries)
            for future in as_completed(futures, timeout=None):
                total += 1
                try:
                    cand = future.result()
                except SystemExit:
                    x.shutdown(wait=True, cancel_futures=True)
                    logger.error("Exiting program.")
                    sys.exit()
                if cand:
                    count += 1
                    yield cand

        for cand in self._process_needs_input_list():
            count += 1
            yield cand

        for cand in self._process_multiple_matches_list():
            count += 1
            yield cand

        logger.info("Found %s candidates out of %s pages", count, total)

    def _process_needs_input_list(self):
        for cand in self.needs_input_list:
            while True:
                newid = self._ask_for_id(cand, cand.suggested_id)
                if newid is None:
                    break
                try:
                    rt_id, rt_data = self._rt_data(cand.title, newid, use_p1258=False)
                except NeedsUserInputError:
                    print(f"Problem getting Rotten Tomatoes data with id {newid}\n")
                    continue
                if rt_data:
                    cand.rt_id, cand.rt_data = rt_id, rt_data
                    yield cand
                break

    def _ask_for_id(self, cand, suggested_id):
        """
        Asks for a user decision regarding the Rotten Tomatoes id for a film.

        Returns:
            if user decides to skip, returns None
            otherwise returns the suggested id or a manually entered id
        """
        title = cand.title
        i, j = cand.span[0], cand.span[2]
        prompt = f"""\033[96mNo working id found for the following candidate:\033[0m
\033[95m{cand.title}\033[0m
\033[95mContext---------------------------------------------------\033[0m
{cand.pagetext[i - 60: i]}\033[1m{cand.pagetext[i: j]}\033[0m{cand.pagetext[j: j+30]}
\033[95m----------------------------------------------------------\033[0m
Please select an option:
    1) use suggested id {suggested_id}
    2) open [[{title}]] and {suggested_id} in the browser
    3) enter id manually
    4) skip this candidate
    5) quit the program"""
        print(prompt)
        while (user_input:=input("Your selection: ")) not in ['1', '3', '4', '5']:
            if user_input == '2':
                webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), title).full_url())
                webbrowser.open(scraper.rt_url(suggested_id))
            else:
                print("Not a valid selection.")

        print()
        if user_input == '1':
            return suggested_id
        elif user_input == '3':
            while not (newid := input("Enter id here: ")).startswith('m/'):
                print('A valid id must begin with "m/".')
            return newid
        elif user_input == '4':
            return None
            logger.info("Skipping article [[%s]]", title)
        elif user_input == '5':
            print("Quitting program."); sys.exit()                


    def _process_multiple_matches_list(self):
        for title in self.multiple_matches_list:
            prompt = f"""\033[96mMultiple matches found in [[{title}]].\033[0m
Please select an option:
    1) open [[{title}]] in the browser for manual editing
    2) skip this article
    3) quit the program"""
            while (user_input := input('Your selection: ')) not in ['2', '3']:
                if user_input == '1':
                    webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), title).full_url())
                    print()
                    prompt2 = f"""When finished in browser:
    1) get current revision of [[{title}]] and process all valid matches found
    2) continue"""
                    while (user_input2 := input('Your selection: ')) not in ['1', '2']:
                        print("\nNot a valid selection.\n")
                    if user_input2 == '1':
                        page = pwb.Page(pwb.Site('en', 'wikipedia'), title)
                        entry = Entry(title, page.text)
                        cl = self.candidate_from_entry(entry, get_all=True, get_user_input=False)
                        for cand in cl:
                            yield cand
                    print()
                    break
                else:
                    print("\nNot a valid selection.\n")
            else:
                print()
                if user_input == '3':
                    print("Quitting program."); sys.exit()


    def _rt_data(self, title, movieid, use_p1258 = True):
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

        logger.debug("Processing potential candidate [[%s]]", title)

        try:
            return movieid, scraper.get_rt_rating(movieid)
        except requests.exceptions.HTTPError as x:
            if x.response.status_code == 403:
                self.blocked.acquire(blocking=False)
                logger.exception("Probably blocked by rottentomatoes.com. Exiting thread")
                sys.exit()
            elif x.response.status_code == 404:
                logger.debug("404 Client Error", exc_info=True)
            elif x.response.status_code == 500:
                logger.debug("500 Server Error", exc_info=True)
            else:
                logger.exception("An unknown HTTPError occured for [[%s]] with id %s", title, movieid)
                raise
        except requests.exceptions.TooManyRedirects as x:
            logger.exception("Too many redirects for [[%s]] with id %s", title, movieid)


        if use_p1258:
            logger.info("Problem getting Rotten Tomatoes data for [[%s]] with id %s. Trying Wikidata property P1258...", title, movieid)
            if p := Recruiter._p1258(title):
                logger.info("Found Wikidata property P1258 for [[%s]]: %s", title, p)

                if p == movieid: # in case it's the same and we already know it fails
                    raise NeedsUserInputError

                try:
                    return p, scraper.get_rt_rating(p)
                except requests.exceptions.HTTPError as x:
                    if x.response.status_code == 403:
                        self.blocked.acquire(blocking=False)
                        logger.exception("Probably blocked by rottentomatoes.com. Exiting thread")
                        sys.exit()
                    elif x.response.status_code == 404:
                        logger.debug("404 Client Error", exc_info=True)
                    elif x.response.status_code == 500:
                        logger.debug("500 Server Error", exc_info=True)
                    else:
                        logger.exception("An unknown HTTPError occured for [[%s]] with id %s", title, p)
                        raise
                except requests.exceptions.TooManyRedirects as x:
                    logger.debug("Too many redirects for [[%s]] with id %s", title, p, exc_info=True)

                logger.info(f'Problem getting Rotten Tomatoes data for [[{title}]] with P1258 value {p}')
            else:
                logger.info(f"Wikidata property P1258 does not exist for [[{title}]]")

        logger.info("Problem getting Rotten Tomatoes data for [[%s]] with id %s", title, movieid)
        raise NeedsUserInputError

    # ===========================================================================================

    @staticmethod
    def _find_span_and_prose(match):
        """
        This function tries find the beginning of
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
        text = text.replace('“', '"').replace('”', '"')
        italics = False
        for i in range(match.start() - 1, -1, -1):
            c = text[i]
            if c in "\n>" or (c == "." and not italics and text[i+1] in ' "'):
                ind = i + 1
                break
            elif c == "'" == text[i + 1]:
                italics = not italics

        while text[ind] in ' "':
            ind += 1

        mid = text.find('<ref', ind)
        end = match.end()
        return (ind, mid, end), text[ ind : end ]


    @staticmethod
    def _find_citation_and_id(title, m, refnames):
        groupdict = m.groupdict()
        ref = Reference('')
        if ldrefname := groupdict.get('ldrefname'):
            ref.reftext = refnames[ldrefname].group()
            ref.refname = ldrefname
            ref.ld = True
            groupdict = refnames[ldrefname].groupdict()
        else:
            ref.reftext = groupdict['citation']
            ref.refname = groupdict.get('refname')

        if rt_id := groupdict.get('rt_id'):
            return ref, rt_id
        elif citert := groupdict.get('citert'):
            d = parse_template(citert)[1]
            return ref, "m/" + d['id']
        elif rt := groupdict.get('rt'):
            d = parse_template(rt)[1]
            if 1 in d.keys() or 'id' in d.keys():
                key = 1 if 1 in d.keys() else 'id'
                return ref, ["m/",""][d[key].startswith("m/")] + d[key]
            elif p := Recruiter._p1258(title):
                return ref, p

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
    def suggested_id(title):
        if x := Recruiter._p1258(title):
            return x
        url = googlesearch.lucky(title + "movie site:rottentomatoes.com/m/")
        suggested_id = url.split('rottentomatoes.com/')[1]
        return suggested_id

if __name__ == "__main__":
    pass



