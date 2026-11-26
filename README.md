# redactor

Finds an erasure poem hidden in a web page, then blacks out everything else.

An erasure keeps some of a source and deletes the rest. Nothing is added, nothing is reordered, and what survives stays where it was on the page. `redactor` enumerates every erasure of a page that satisfies a given form, ranks them, and renders the winner as a redacted screenshot.

## The problem it solves

A form alone is not a constraint worth having. The 43-word opening of _Moby-Dick_ contains 15,829,992,033 valid 5/7/5 erasures, and essentially all of them are word salad:

```
Call me Some never / how precisely, having no / me on thought a the
```

Three filters cut that to something a reader can be shown. Measured on the same paragraph:

| constraint                 | candidates     |
| -------------------------- | -------------- |
| none                       | 15,829,992,033 |
| POS bigram                 | 6,858,150,007  |
| POS trigram                | 75,156,809     |
| contiguity, 3 runs         | 89,813         |
| contiguity, 2 runs         | 1,643          |
| contiguity 2 + POS trigram | 102            |

Contiguity does nearly all the work. The reason is better than the number: the source is already grammatical, so keeping its spans intact inherits its syntax outright, with no parser and no model. Part-of-speech transitions only check tag pairs, which is a much weaker proxy for the same thing.

At 102 the whole set can be enumerated and read, so a model never has to generate anything. It ranks. That removes invented words, miscounted syllables and reordered lines as possibilities rather than as bugs to catch.

## Use

```sh
redactor https://example.com/some-page
redactor https://example.com --form tanka --runs 3
redactor https://example.com --no-image        # text only, no screenshot
redactor https://example.com --no-llm --seed 7 # deterministic, no API calls
```

Forms: `haiku`, `tanka`, `lune`, `cinquain`, `fib`, `pentameter`.

With no `ANTHROPIC_API_KEY` the pipeline still completes. It picks arbitrarily from the candidate set, and the result is still form-correct and still readable. It just isn't chosen.

## Requirements

Python 3.11, plus `tesseract` and ImageMagick's `magick` for the rendered output, and a Chrome or Chromium binary for the screenshot. `--no-image` needs none of those.

Part-of-speech pruning is optional. Install `spacy` and `en_core_web_sm` to enable it; without them the contiguity limit carries the pruning on its own.

## What does not work

Mesostics, acrostics and concrete verse cannot be erasures. An erasure may only delete, so it inherits the source's layout, while those forms need a constructed one: a mesostic wants its spine letters stacked at a single x position, and no page will supply that by accident. Measured on 506 words of a real page, a strict Cage mesostic with any vertical descent requirement has zero solutions.

Forms that constrain which words survive compose fine. Forms that dictate where words sit do not.
