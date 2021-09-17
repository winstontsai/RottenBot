# RottenBot
A bot to help edit [Rotten Tomatoes](https://www.rottentomatoes.com) data on [Wikidata](https://www.wikidata.org/wiki/Wikidata:Main_Page) and the [English Wikipedia](https://en.wikipedia.org/wiki/Main_Page).

## Description
Many film articles on Wikipedia contain Rotten Tomatoes data for the film. For some examples, visit [Titanic](https://en.wikipedia.org/wiki/Titanic_(1997_film)), [Black Widow](https://en.wikipedia.org/wiki/Black_Widow_(2021_film)), and [Casablanca](https://en.wikipedia.org/wiki/Casablanca_(film)). RottenBot keeps this info up to date by replacing raw Rotten Tomatoes info in the [wikitext](https://en.wikipedia.org/wiki/Help:Wikitext) with a template ([Template:Rotten Tomatoes data](https://en.wikipedia.org/wiki/Template:Rotten_Tomatoes_data)) which retrieves the latest Rotten Tomatoes info from Wikidata, while keeping most of the original wikitext intact. In particular, RottenBot stores Rotten Tomatoes info in Wikidata for this template to use.

RottenBot also has a simple flagging system to prevent certain undesirable edits from being made. Flagged edits must be reviewed and cleared by the bot operator in order to be uploaded.

## Limitations
The bot does not handle [shortened footnote](https://en.wikipedia.org/wiki/Help:Shortened_footnotes) citation styles or [link rot](https://en.wikipedia.org/wiki/Wikipedia:Link_rot) if the movie has been removed from Rotten Tomatoes.

## See Also
* [Rotten Tomatoes FAQ](https://www.rottentomatoes.com/faq)
* [RottenBot's Request for Permissions on Wikidata](https://www.wikidata.org/wiki/Wikidata:Requests_for_permissions/Bot/RottenBot)
* [RottenBot's Request for Approval on Wikipedia](https://en.wikipedia.org/wiki/Wikipedia:Bots/Requests_for_approval/RottenBot)
* [RottenBot's User Page on Wikipedia](https://en.wikipedia.org/wiki/User:RottenBot)
