# This module takes Candidates and computes produces the new text to be used.
# 
# FIXES
# 0. Add flags for multiple references, suspicious start, suspicious end, too many quotes
# 1. build new prose, using full prose replacement if missing average or count,
#    and adding flags for multiple average, multiple count, or multiple score
# 3. tack on critical consensus if safe
# 4. tack citation
# 5. return Edit object


import re
import sys
import webbrowser
import logging

from dataclasses import dataclass


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
    replacements: list[tuple[str, str]]
    flags: list[str]


class Editor:

    def compute_edits(self, candidates, user_input = True):
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
        for cand in candidates:
            e = Editor.compute_edit(cand)
            if e:
                yield e

    @staticmethod
    def compute_edit(cand):
        rt_data = cand.rt_data
        if not rt_data:
            return None

        span, pagetext, flags = cand.span, cand.pagetext, list()
        old_prose = pagetext[span[0] : span[1]]

        # set new_prose to the old_prose without the references
        # we will update/build up new_prose step by step in the sequel
        new_prose = old_prose

        if cand.prose.count('<ref') > 1:
            flags.append("multiple refs")

        # check for some suspicious characters
        if old_prose[0] not in "[{'ABCGIORTW1234567890":
            flags.append("suspicious start")

        if old_prose[-1] not in '."}' and cand.prose[-1] != '.' and pagetext[span[2]] != '\n':
            flags.append("suspicious end")

        # First deal with template {{Rotten Tomatoes prose}}
        if m := re.match(t_rtprose, new_prose):
            new_prose = '{{Rotten Tomatoes prose|' + f'{rt_data["score"]}|{rt_data["average"]}|{rt_data["reviewCount"]}' + '}}'
        else:
            # NOWHERE DOES IT SAY IT'S A WEIGHTED AVERAGE
            if re.search("[wW]eighted", new_prose):
                new_prose = prose_replacement(cand)

            # Remove as of date
            if re.search("[Aa]s ?of", new_prose):
                new_prose = prose_replacement(cand)

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
            all_scores = re.findall(score_re, old_prose)
            if len(all_scores)>1 and set(all_scores) not in ({'0%'}, {'100%'}):
                flags.append("multiple scores")
            elif len(all_scores) > 1 and f"{rt_data['score']}%" != all_scores[0]:
                flags.append("multiple scores")
            new_prose= re.sub(score_re, f"{rt_data['score']}%", new_prose)


        # add consensus if safe
        if rt_data["consensus"] and 'consensus' not in new_prose and not re.match('[^\n]* consensus', pagetext[span[2]:]):
            new_prose += " " + consensus_prose(cand)

        # fix period/quote situation
        if new_prose.endswith('.".'):
            new_prose = new_prose[:-1]
        elif new_prose.endswith('".'):
            new_prose = new_prose[:-2] + '."'

        # if no change, don't produce an edit
        if new_prose == old_prose:
            return None

        # add reference and create replacements list
        if cand.ld: # list-defined reference requires two replacements
            new_prose += f'<ref name="{cand.refname}" />'
            replacements = [(cand.prose, new_prose),
                            (cand.citation, citation_replacement(cand))]
        else:
            new_prose += citation_replacement(cand)
            replacements = [(cand.prose, new_prose)]

        return Edit(cand.title, replacements, flags)

    @staticmethod
    def make_replacements(edit_list):
        site = pwb.Site('en', 'wikipedia')
        not_edited = list()
        for edit in edit_list:
            page = pwb.Page(site, edit.title)
            for old, new in edit.replacements:
                if old in page.text:
                    page.text = page.text.replace(old, new)
                else:
                    not_edited.append(edit.title)
                    break
            else:
                page.save()
        return not_edited

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








