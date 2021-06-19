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
        if self.blocked.locked():
            sys.exit()

        title = entry.title

        logging.debug(f"candidate_from_entry {title}")

        self.patterns = [cand_re1, cand_re2]

        # Get allowed refnames. Dictionary mapping name to definition
        refnames = dict()
        for m in re.finditer(fr'(?P<citation><ref +name *= *"?(?P<refname>[^>]+?)"? *>((?!<ref).)*{t_alternates}((?!<ref).)*</ref *>)', entry.text, flags=re.DOTALL):
            refnames[re.escape(m.group('refname'))] = m.group()

        if refnames:
            allowed_refname = alternates(refnames)

            ldref_re = fr'(?P<ldref><ref +name *= *"?(?P<ldrefname>{allowed_refname})"? */>)'
            ldref_re2 = fr'(?P<ldref2><ref +name *= *"?(?P<ldrefname2>{allowed_refname})"? */>)'
            rtref_re2 = alternates([citation_re2,ldref_re2])

            cand_re3 = rt_re + r"[^\n<>]*?" + score_re + r"[^\n]*?" + ldref_re +    fr'([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'
            cand_re4 = score_re + r"[^\n<>]*?" + rt_re + r"[^\n]*?" + ldref_re +    fr'([^\n.]*? consensus[^n]*?".*?"[.]?{rtref_re2}?)?(?![^\n]* consensus)'
            self.patterns += [cand_re3, cand_re4]


        for p in self.patterns:
            # if x := list(re.finditer(p, entry.text, flags=re.DOTALL)):
            #     if len(x) > 1:
            #         print([m.group() for m in x])
            #         print()

            if m := re.search(p, entry.text, flags=re.DOTALL):

                # This is mostly just for list-defined references
                if not (citation := Recruiter._find_citation(m)):
                    logging.info(f"No citation found for [[{title}]] with match {m.group()}")
                    continue

                return Candidate(title, m.group(),
                    self._find_prose(m), citation, '', {})

                rt_id = Recruiter._find_id(citation,title)
                try:
                    rt_id, rt_data = self._rt_data(title, rt_id)
                except NeedsUserInputError:
                    if self.get_user_input:
                        self.needs_input_list.append((title, m, citation))
                else:
                    if rt_data:
                        return Candidate(
                            title=title,
                            text=m.group(),
                            prose=self._find_prose(m),
                            citation=citation,
                            rt_id=rt_id,
                            rt_data=rt_data)

        return None # not a candidate

    def candidate_from_entry2(self, entry):
        if self.blocked.locked():
            sys.exit()

        title = entry.title

        logging.debug(f"candidate_from_entry2 {title}")

        # Get allowed refnames
        refnames = []
        for m in re.finditer(citation_re, entry.text, flags=re.DOTALL):
            if refname := m.group('refname'):
                refnames.append(refname)
        # add quote possibilities
        refnames += [f'"{refname}"' for refname in refnames]

        allowed_refnames = alternates(refnames)

        matches = []

        for p in self.patterns:
            for m in re.finditer(f"(?=({p}))", entry.text, flags=re.DOTALL):
                if citation := Recruiter._find_citation(m):
                    text = m.group()
                    prose = self._find_prose(m)
                    rt_id = ''
                    matches.append(m.group(1))

        if not matches:
            return None
        elif len(matches) > 1:
            print("\n\n".join(matches))
            print()
            return Candidate(title, '',
                '', '', '', {})




    def find_candidates(self):
        """
        Given an XmlDump, yields all pages (as a Candidate) in the dump
        which match at least one pattern in patterns.
        """
        logging.info(f"Finding candidates with patterns {self.patterns}")

        total, count = 0, 0
        xml_entries = XmlDump(self.filename).parse()

        # save pages which need user input for the end
        self.needs_input_list = []

        # if we get blocked (status code 403), add something to this queue
        # if Queue is empty, then not blocked.
        # if Queue is not empty, then we got blocked
        # self.blocked = Queue()
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

        for title, m, citation in self.needs_input_list:
            rt_id, rt_data = self._bad_try("", entry.title, user_input_mode=True)
            if rt_data:
                count += 1
                yield Candidate(
                    title=entry.title,
                    text=m.group(),
                    prose=self._find_prose(m),
                    citation=citation,
                    rt_id=rt_id,
                    rt_data=rt_data)


        logger.info("Found %s candidates out of %s pages", count, total)


    def _rt_data(self, title, movieid):
        """
        Three possible return values.
        1. id, data. The rating data we want.
        2. _ , none. Which means there is no rating data, or the user opted to skip.
        3. id, empty dict. Which happens when the rating data exists but
        Rotten Tomatoes is having trouble loading the rating data for a movie.
        """
        if self.blocked.locked():
            sys.exit()

        logger.info("Processing potential candidate [[%s]]", title)
        return self._get_data(movieid, title, self._bad_first_try)



    def _get_data(self, movieid, title, func, *args, **kwargs):
        """
        Tries to return the Rotten Tomatoes data for a movie.
        Executes func if there is a requests.exceptions.HTTPError.
        Func is meant to be a function which returns the desired Rotten Tomatoes data
        in a tuple (id, data).
        """
        if self.blocked.locked():
            raise sys.exit()

        try:
            return movieid, scraper.get_rt_rating(rt_url(movieid))
        except requests.exceptions.HTTPError as x:
            if x.response.status_code == 403:
                self.blocked.acquire()
                logger.exception("Probably blocked by rottentomatoes.com. Exiting thread")
                sys.exit()
            elif x.response.status_code == 404:
                logger.exception("404 Client Error")
            elif x.response.status_code == 500:
                logger.exception("500 Server Error")
            else:
                logger.exception("An unknown HTTPError occured for [[%s]] with id %s", title, movieid)
                raise
            return func(movieid, title, *args, **kwargs)
        except requests.exceptions.TooManyRedirects as x:
            logger.exception("Too many redirects for [[%s]] with id %s", title, movieid)
            return func(movieid, title, *args, **kwargs)

    def _bad_first_try(self, movieid, title):
        logger.info("Problem getting Rotten Tomatoes data for [[%s]] from id %s. Checking for Wikidata property P1258...", title, movieid)
        if p := Recruiter._p1258(title):
            logger.debug("Found Wikidata property P1258 for [[%s]]: %s", title, p)
            msg = f'Problem getting Rotten Tomatoes data for [[{title}]] with P1258 value {p}'
            if p == movieid:
                return self._bad_try(movieid, title, msg)
            return self._get_data(p, title, self._bad_try, msg)
        else:
            msg = f"Wikidata property P1258 does not exist for [[{title}]]"
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
                logger.info("Problem getting Rotten Tomatoes data for [[%s]] from id %s", title, movieid)
            logger.debug("[[%s]] will need user's input", title)
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

        prompt = f"""Please select an option for [[{title}]]:
    1) use suggested id {suggested_id}
    2) open the suggested id's Rotten Tomato page and [[{title}]] in the browser
    3) enter id manually
    4) skip this article
    5) quit the program
Your selection: """

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
            logger.info("Skipping article [[%s]]", title)
        elif user_input == '5':
            print("Quitting program."); sys.exit()





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

        if 'citation' in match.groupdict() and match.group('citation'):
            end = match.start('citation')
        else:
            end = match.start('ldref')
        return text[ind : end]



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
    def _find_id(citation, title):
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
            logger.error("Could not find a Rotten Tomatoes ID from the following citation: %s", citation)
            raise ValueError("Could not find a Rotten Tomatoes ID from the following citation: {}".format(citation))
        else:
            logger.debug('Found id %s from the citation "%s"', answer, citation)

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











