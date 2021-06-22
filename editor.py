# This module takes Candidates and computes produces the new text to be used.
# `
# FIXES
# 0. If multiple matches in the page, needs manual edit
# 1. swap " and .
# 2. update score
# 3. update count
# 4. update average
# 5. add critical consensus if ' consensus' does not appear in the sequel
# 6. Check if more than one reference. If so, needs manual edit.
# 7. Use full replacement if no count, no average, or no critical consensus.
# 8. If any edit will be made, change the citation to use Cite Rotten Tomatoes template.


import re
import sys
import webbrowser
import logging

from dataclasses import dataclass, field

import pywikibot as pwb

from patterns import *




def prose_replacement(cand, d, add_consensus = False):
    s = "On review aggregator [[Rotten Tomatoes]], the film holds an approval rating \
of {}% based on {} reviews, with an average rating of {}/10.".format(d['score'], d['reviewCount'], d['average'])
    if add_consensus and d['consensus']:
        s += " The website's critical consensus reads, \"{}\"".format(d['consensus'])

    # add citation
    # s += "<ref>{{{{Cite Rotten Tomatoes |id={} |type=movie |title={} |access-date={}}}}}</ref>".format(cand.rt_id[2:], d['title'], d['accessDate'])

    return s

def citation_replacement(rt_data, refname = None):
    s = "<ref"
    if refname:
        s += f' name="{refname}">'
    else:
        s += '>'
    s += f"{{{{Cite Rotten Tomatoes |id={rt_data['id']} |type=movie |title={rt_data['title']} |access-date={rt_data['accessDate']}}}}}</ref>"
    return s


@dataclass
class Edit:
    title: str
    replacements: list[tuple[str, str]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


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
        for cand in list(self.recruiter.find_candidates()):
            e = self._compute_edit(cand, suspects)
            if e:
                yield e

    def _compute_edit(self, cand, suspect_list):
        old_prose, old_citation = cand.prose, cand.citation
        rt_data = cand.rt_data
        flags = []

        if old_prose.count('<ref') > 1:
            flags.append("multiple refs")

        # check for some suspicious first and last characters
        if old_prose[0] not in "[{'ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            flags.append("suspicious start")

        ref_start = old_prose.find('<ref')
        if old_prose[ref_start - 1] not in '."':
            flags.append("suspicious end")
        if old_prose[:ref_start].count('"') > 2:
            flags.append("too many quotes")

        add_consensus = not re.match('[^\n]* consensus', cand.pagetext[cand.start:])


        new_prose = old_prose[:ref_start] # will be transformed step-by-step into new prose

        # handle average rating     
        new_prose, k = re.subn(average_re, f'{rt_data["average"]}/10', new_prose)
        if k == 0:
            return "FULL REPLACEMENT"
        elif k > 1:
            flags.append("multiple averages")
            
        # handle review reviewCount
        new_prose, k = re.subn(count_re, f"{rt_data['reviewCount']} \g<count_term>", new_prose)
        if k == 0:
            return "FULL REPLACEMENT"
        elif k > 1:
            flags.append("multiple counts")

        # handle score
        new_prose, k = re.subn(score_re, f"{rt_data['score']}%", new_prose)
        if k > 1:
            flags.append("multiple scores")

        # fix period/quote situation
        if new_prose.endswith('.".'):
            new_prose = new_prose[:-1]
        elif new_prose.endswith('".'):
            new_prose = new_prose[:-2] + '."'

        if new_prose == old_prose[:ref_start]:
            return None

        # add reference
        if cand.ld:
            new_prose += f'<ref name="{cand.refname}" />'
            replacements = [(old_prose, new_prose),
                            (cand.citation, citation_replacement(rt_data, cand.refname))]
        else:
            new_prose += citation_replacement(rt_data, cand.refname)
            replacements = [(old_prose, new_prose)]

        return Edit(cand.title, replacements, flags)

    @staticmethod
    def make_replacements(edit):
        page = pwb.Page(pwb.Site('en', 'wikipedia'), edit.title)
        for old, new in edit.replacements:
            if old in page.text:
                page.text = page.text.replace(old, new)
            else:
                return False
        page.save()
        return True

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
            while (user_input := input(prompt)) not in ['1', '2', '3', '4']:
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




if __name__ == "__main__":
    print(citation_replacement({'id': 'titanic', 'title': 'TITLE HAAH', 'accessDate': 'June 2, 2021'}, refname="Finding Nemo"))








