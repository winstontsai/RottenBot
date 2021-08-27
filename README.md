# RottenBot
A [bot](https://en.wikipedia.org/wiki/Wikipedia:Bots) to help edit [Rotten Tomatoes](https://www.rottentomatoes.com/) data on the [English Wikipedia](https://en.wikipedia.org/wiki/Main_Page).

For some example edits, see [example_edits.txt](https://github.com/winstontsai/RottenBot/blob/master/example_edits.txt).

## Description
Many film articles on Wikipedia contain Rotten Tomatoes data for the film. For some examples, visit [Titanic](https://en.wikipedia.org/wiki/Titanic_(1997_film)), [Black Widow](https://en.wikipedia.org/wiki/Black_Widow_(2021_film)), and [Casablanca](https://en.wikipedia.org/wiki/Casablanca_(film)). RottenBot keeps the numbers up to date. It also adds missing info, updates/adds citations, and performs other minor fixes.

There is no consensus on the wording of Rotten Tomatoes prose on Wikipedia. In particular, a bot which rewrites every article's Rotten Tomatoes prose into a uniform format would likely not obtain community approval. Hence RottenBot keeps most of the original [wikitext](https://en.wikipedia.org/wiki/Help:Wikitext) where it can, but makes some discretionary modifications. In particular, RottenBot performs a complete rewrite of the original prose if the original prose cannot be safely updated automatically.

RottenBot also has a simple flagging system to prevent undesirable or otherwise overzealous edits from being made. Flagged edits need to be reviewed and cleared by the bot operator in order for the edit to be uploaded.

## See Also
* [RottenBot's Wikipedia User Page](https://en.wikipedia.org/wiki/User:RottenBot)
* [RottenBot's Request for Approval](https://en.wikipedia.org/wiki/Wikipedia:Bots/Requests_for_approval/RottenBot)
* [Wikipedia Manual of Style for Film](https://en.wikipedia.org/wiki/Wikipedia:Manual_of_Style/Film)
* [Rotten Tomatoes FAQ](https://www.rottentomatoes.com/faq)
