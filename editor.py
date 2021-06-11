# This module takes Candidates and computes produces the new text to be used.

import re
import sys
import webbrowser

import pywikibot as pwb
import candidates
from patterns import *




class Edit:

    def __init__(self, cand, new_prose, new_citation, handler, flags):
        self.title = cand.title
        self.rt_id = cand.rt_id
        self.old_prose = cand.prose
        self.new_prose = new_prose
        self.old_citation = cand.citation
        self.new_citation = new_citation
        # Anticipated flags, some probably won't be used:
        # fully_replaced
        # suspicious_start
        # suspicious_end
        # multiple_average
        # multiple_count
        # multiple_score
        self.flags = flags
        # Handler function for the edit.
        self.handler = handler

    def to_dict(self):
        d = dir(self)
        return {k: getattr(self, k) for k in ["title", "rt_id", "old_prose",
            "new_prose", "old_citation", "new_citation", "flags"]}

class Editor:

    def __init__(self, recruiter):
        self.recruiter = recruiter


    def compute_edits(self, user_input = True):
        """
        Takes the candidates that the recruiter provides and computes
        the edits needed for each candidate.
        Yields these as Edit objects.
        Suspicious edits may either be yielded, or they may be manually
        implemented, depending on the user's input.

        Args:
            user_input: if True, suspicious edits will require user input
            to be handled. Otherwise suspicious edits will be ignored.
        """

        # Suspect list of suspicious edits.
        suspects = []

        for cand in self.recruiter.find_candidates():
            e = self._compute_edit(cand, suspects)
            if e:
                yield e
        for suspect in suspects:
            yield e


    def _compute_edit(self, cand, suspect_list):
        flags = []
        # check for some suspicious first and last characters
        if cand.prose[0] not in "[{'ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            flags.append("suspicious_start")
            handler = Editor._suspicious_start_handler
        elif "consensus" in cand.prose and cand.prose[-1] != '"':
            flags.append("suspicious_end")
            handler = Editor._suspicious_end_handler
        elif "consensus" not in cand.prose and cand.prose[-1] != '.':
            flags.append("suspicious_end")
            handler = Editor._suspicious_end_handler
        else:
            handler = Editor._replacement_handler

        d = cand.rt_data
        if not d:
            return None

        old_prose = cand.prose
        new_prose = cand.prose # used to build up the new prose


        # handle average rating     
        new_prose, k = re.subn(average_re, d['average']+'/10', new_prose)
        if k == 0:
            return Edit(cand, new_prose=full_replacement(cand, d), new_citation='',
                handler=handler, flags=flags)
        elif k > 1:
            flags.append("multiple_average_handler")
            handler = Editor._multiple_average_handler


        # handle review reviewCount
        if not (m := re.search(count_re, old_prose)):
            return Edit(cand, new_prose=full_replacement(cand, d), new_citation='',
                handler=handler, flags=flags)
        elif m.group().endswith("reviews"):
            repl = d['reviewCount'] + " reviews"
        else:
            repl = d['reviewCount'] + " critics"

        new_prose, k = re.subn(count_re, repl, new_prose)
        if k > 1:
            flags.append("multiple_count")
            handler = Editor._multiple_count_handler


        # handle score
        old_score = cand.match.group('score')
        new_prose, k = re.subn(old_score, d['score'] + '%', new_prose)
        if k > 1 and not (old_score.startswith("0") or old_score.startswith("100")):
            handler = Editor._multiple_score_handler


        if new_prose != old_prose:
            return Edit(cand, new_prose=new_prose, new_citation='',
                handler=handler, flags = flags)

        return None

    @staticmethod
    def make_replacement(edit):
        page = pwb.Page(pwb.Site('en', 'wikipedia'), edit.title)
        page.text = page.text.replace(edit.old_prose, edit.new_prose)
        page.text = page.text.replace(edit.old_citation, edit.new_citation)
        page.save()

    @staticmethod
    def _replacement_handler(edit, interactive = True, dryrun = True):
        if interactive:
            print(">>> {} <<<\n".format(edit.title))
            print("Old prose:")
            print(edit.old_prose + '\n')
            print("New prose:")
            print(edit.new_prose + '\n')
            prompt = """Select an option:
    1) yes
    2) no (skip this edit)
    3) open [[{}]] in browser for manual editing
    4) quit program
Your selection: """.format(edit.title)
            while (user_input := input(prompt)) not in "1234":
                pass

            if user_input == '1':
                pass
            elif user_input == '3':
                webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), edit.title).full_url())
                input("Press Enter when finished in browser.")
            elif user_input == '2':
                print("Skipping edit for [[{}]].".format(edit.title))
                return
            elif user_input == '4':
                print("Quitting program.")
                quit()

        if dryrun:
            return
        Editor.make_replacement(edit)

    @staticmethod
    def _suspicious_start_handler(edit, interactive = True, dryrun = True):
        if not interactive:
            return
        print("Suspicious first character '{}' for [[{}]] detected.".format(edit.old_prose[0],
            edit.title))
        print("Here is the old prose:")
        print(edit.old_prose + '\n')
        print("Here is the new prose:")
        print(edit.new_prose + '\n')
        prompt = """Select an option:
    1) replace old prose with new prose
    2) open browser for manual editing
    3) skip this edit
    4) quit the program.
Your selection: """
        while (user_input := input(prompt)) not in "1234":
            pass

        if user_input == '1':
            if dryrun:
                return
            Editor.make_replacement(edit)
        elif user_input == '2':
            webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), edit.title).full_url())
            input("Press Enter when finished in browser.")
        elif user_input == '3':
            print("Skipping edit for [[{}]].".format(edit.title))
            return
        elif user_input == '4':
            print("Quitting program.")
            quit()

    @staticmethod
    def _suspicious_end_handler(edit, interactive = True, dryrun = True):
        if not interactive:
            return
        print("Suspicious last character '{}' for [[{}]] detected.".format(edit.old_prose[-1],
            edit.title))
        print("Here is the old prose:")
        print(edit.old_prose + '\n')
        print("Here is the new prose:")
        print(edit.new_prose + '\n')
        prompt = """Select an option:
    1) replace old prose with new prose
    2) open browser for manual editing
    3) skip this edit
    4) quit the program.
Your selection: """
        while (user_input := input(prompt)) not in "1234":
            pass

        if user_input == '1':
            if dryrun:
                return
            page = pwb.Page(pwb.Site('en', 'wikipedia'), edit.title)
            page.text = page.text.replace(edit.old_prose, edit.new_prose)
            page.text = page.text.replace(edit.old_citation, edit.new_citation)
            page.save()
        elif user_input == '2':
            webbrowser.open(pwb.Page(pwb.Site('en', 'wikipedia'), edit.title).full_url())
            input("Press Enter when finished in browser.")
        elif user_input == '3':
            print("Skipping edit for [[{}]].".format(edit.title))
            return
        elif user_input == '4':
            print("Quitting program.")
            quit()

    @staticmethod
    def _multiple_average_handler(edit, interactive = True):
        print("multiple_average_handler")

    @staticmethod
    def _multiple_count_handler(edit, interactive = True):
        print("multiple_count_handler")

    @staticmethod
    def _multiple_score_handler(edit, interactive = True):
        print("multiple_score_handler")


def full_replacement(cand, d):
    s = "On review aggregator [[Rotten Tomatoes]], the film holds an approval rating \
of {}% based on {} reviews, with an average rating of {}/10.".format(d['score'], d['reviewCount'], d['average'])
    if d['consensus']:
        s += " The website's critical consensus reads, \"{}\"".format(d['consensus'])

    # add citation
    # s += "<ref>{{{{Cite Rotten Tomatoes |id={} |type=movie |title={} |access-date={}}}}}</ref>".format(cand.rt_id[2:], d['title'], d['accessDate'])

    return s




if __name__ == "__main__":
    pass








