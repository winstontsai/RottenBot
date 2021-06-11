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
                    citation, rt_id = self._extract_citation_and_id(entry.title, m, entry.text)
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

        print("CANDIDATES / TOTAL = {} / {}".format(count, total))


    def _p1258(self, title):
        page = pwb.Page(pwb.Site('en','wikipedia'), title)
        item = pwb.ItemPage.fromPage(page)
        item.get()
        if 'P1258' in item.claims:
            return item.claims['P1258'][0].getTarget()
        return None


    def _extract_citation_and_id(self, title, match, text, citation = None):
        """
        Given the re.Match object which has identified a candidate, extracts the movieid.
        """
        if citation is None:
            citation = text[match.start('citation') : match.end()]

        # Cite web template case
        if s := match.group('citeweb'):
            return (citation, match.group('rt_id'))

        # Cite Rotten Tomatoes template case
        if s := match.group('citert'):
            d = parse_template(s)[1]
            return (citation, "m/" + d['id'])

        # Rotten Tomatoes template case 
        if s:= match.group('rt'):
            d = parse_template(s)[1]
            if 1 in d.keys() or 'id' in d.keys():
                key = 1 if 1 in d.keys() else 'id'
                return (citation, ["m/",""][d[key].startswith('m/')] + d[key])

            # Check for Wikidata property P1258
            if p := self._p1258(title):
                return (citation, p)

        if refname := match.group('ldrefname'):
            print("WTF", match.groupdict())
            p = "<ref name ?= ?" + refname + " ?>" + alternates([t_citeweb, t_citert, t_rt])
            m = re.search(p, text)
            citation = m.group()
            print("LDREF CITATION:", citation)
            # Technically it's possible that we didn't find the definition of the
            # reference with the above pattern, either because it doesn't exist
            # or we have an abnormal situation like one uses quotes while the other does not.
            # But I think that's unlikely.
            # If it happens, then the above will throw an exception.
            return (citation, self._extract_citation_and_id(title, m, text, citation)[1])


        raise ValueError("Could not find the Rotten Tomatoes ID for [[{}]].".format(title))


    def _rt_data(self, title, movieid):
        print(title, flush=True)
        data = self._get_data(movieid, title, self._bad_first_try)
        if data:
            return data
        elif data == {}:
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


        newid = self._ask_for_id(title)
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


    def _ask_for_id(self, title, msg = None):
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
                webbrowser.open(rt_url(suggested_id))
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
        else: # list-defined reference case
            refname = match.group('ldrefname')
            p = "<ref name ?= ?{} ?>{}".format(refname, alternates([t_citeweb, t_citert, t_rt]))
            m = re.search(p, text)
            # Technically it's possible that we didn't find the definition of the
            # reference with name refname and hence m == None,
            # but I think that's unlikely.
            # If it happens an exception will occur and we'll know.
            return m.group()


if __name__ == "__main__":
    pass











