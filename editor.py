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

def consensus_prose(cand):
    d = cand.rt_data
    return f'The website\'s critical consensus reads, "{d["consensus"]}"'

def prose_replacement(cand):
    d = cand.rt_data
    return f"On review aggregator [[Rotten Tomatoes]], the film holds an approval rating \
of {d['score']}% based on {d['reviewCount']} reviews, with an average rating of {d['average']}/10."

def citation_replacement(cand):
    d, refname = cand.rt_data, cand.refname
    s = "<ref"
    if refname:
        s += f' name="{refname}">'
    else:
        s += '>'
    s += f"{{{{Cite web |url={d['url']} |title={d['title']} |website=[[Rotten Tomatoes]] |publisher=[[Fandango Media]] |access-date={d['accessDate']}</ref>"
    #s += f"{{{{Cite Rotten Tomatoes |id={d['id']} |type=movie |title={d['title']} |access-date={d['accessDate']}}}}}</ref>"
    return s

def full_replacement(cand, add_consensus = False):
    s = prose_replacement(cand)
    if add_consensus and cand.rt_data['consensus']:
        s += ' ' + consensus_prose(cand)
    s += citation_replacement(cand)
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
            e = self._compute_edit(cand)
            if e:
                yield e

    def _compute_edit(self, cand):
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

        new_prose = old_prose[:ref_start] # will be transformed step-by-step

        # First deal with template {{Rotten Tomatoes prose}}
        if m := re.match(t_rtprose, new_prose):
            new_prose = '{{Rotten Tomatoes prose|' + f'{rt_data["score"]}|{rt_data["average"]}|{rt_data["reviewCount"]}' + '}}'
        else:
            # handle average rating     
            new_prose, k = re.subn(average_re, f'{rt_data["average"]}/10', new_prose)
            if k == 0:
                new_prose = prose_replacement(cand)
            elif k > 1:
                flags.append("multiple averages")
                
            # handle review reviewCount
            new_prose, k = re.subn(count_re, f"{rt_data['reviewCount']} \g<count_term>", new_prose)
            if k == 0:
                new_prose = prose_replacement(cand)
            elif k > 1:
                flags.append("multiple counts")

            # handle score
            new_prose, k = re.subn(score_re, f"{rt_data['score']}%", new_prose)
            if k > 1:
                flags.append("multiple scores")

        # add consensus if safe
        if cand.rt_data["consensus"] and not re.match('[^\n]* consensus', cand.pagetext[cand.start:]):
            new_prose += " " + consensus_prose(cand)

        # fix period/quote situation
        if new_prose.endswith('.".'):
            new_prose = new_prose[:-1]
        elif new_prose.endswith('".'):
            new_prose = new_prose[:-2] + '."'

        # if no change, don't produce an edit
        if new_prose == old_prose[:ref_start]:
            return None

        # add reference and create replacements list
        if cand.ld: # list-defined reference requires two replacements
            new_prose += f'<ref name="{cand.refname}" />'
            replacements = [(old_prose, new_prose),
                            (cand.citation, citation_replacement(cand))]
        else:
            new_prose += citation_replacement(cand)
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
    pass








