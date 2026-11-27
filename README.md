# redactor

Finds an erasure poem hidden in a web page, then blacks out everything else.

Pointed at the Hacksgiving rules page, it produced this:

```
as you want it to be. Your agent we
```

Ten syllables, iambic, and a true subsequence of Fly's own copy. 1,268 erasures of that page scan as pentameter. A model picked this one and said it "turns the page's product instructions into a quiet ending where 'Your agent' turns into 'we,' as if the tool you shape to your wishes ends up being you."

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

## Forms

`--form auto` is the default. It climbs to the hardest form the page will admit and tells you which one that was.

Difficulty here is measured, not asserted: it is how rarely a page admits the form at all. Of the erasures of 260 words that fit by syllable count, these fractions also scan.

| form         | admits | kind                        |
| ------------ | ------ | --------------------------- |
| `ballad`     | 0.01%  | 8 6 8 6, alternating stress |
| `pentameter` | 12.54% | 10 syllables, 0101010101    |
| `tetrameter` | 20.34% | 8 syllables, 01010101       |
| `fib`        | 100%   | 1 1 2 3 5 8                 |
| `cinquain`   | 100%   | 2 4 6 8 2                   |
| `tanka`      | 100%   | 5 7 5 7 7                   |
| `lune`       | 100%   | 5 3 5                       |
| `haiku`      | 100%   | 5 7 5                       |

The syllabic forms admit everything that fits them because they have no stress requirement to fail.

Ordering by difficulty buys more than a badge. A tight metrical form can only be satisfied by long contiguous spans, so its output inherits the source's grammar wholesale and reads better than a loose form's. Harder is not a trade against sense. It buys sense.

### Word-level shapes

`--shape snowball` and friends constrain which words survive and say nothing about lines, so the page supplies the layout.

`snowball` (each word a letter longer than the last), `univocalic:o`, `lipogram:e`, `abecedarian`, `chain`.

These sit at the bottom of the ladder and are only reached automatically when no form fits. A snowball is legible as a rule and almost never as a sentence:

```
a / it / the / week. / Start / Ollama / exactly / partners / connector / guidelines / Hacksgiving
```

## Publishing

`--publish owner/repo` writes the result through the GitHub Sprites connector: the poem, the render, and the provenance to check it. From inside a Sprite the gateway identifies the caller by Fly's request signature, so no token is read, stored or passed.

With no `ANTHROPIC_API_KEY` the pipeline still completes. It picks arbitrarily from the candidate set, and the result is still form-correct and still readable. It just isn't chosen.

## Requirements

Python 3.11, plus `tesseract` and ImageMagick's `magick` for the rendered output, and a Chrome or Chromium binary for the screenshot. `--no-image` needs none of those.

Part-of-speech pruning is optional. Install `spacy` and `en_core_web_sm` to enable it. Without them the contiguity limit carries the pruning on its own.

## What does not work

Mesostics, acrostics and concrete verse cannot be erasures. An erasure may only delete, so it inherits the source's layout, while those forms need a constructed one: a mesostic wants its spine letters stacked at a single x position, and no page will supply that by accident. Measured on 506 words of a real page, a strict Cage mesostic with any vertical descent requirement has zero solutions.

Forms that constrain which words survive compose fine. Forms that dictate where words sit do not.
