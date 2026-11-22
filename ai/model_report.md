# Title classifier: model report

Generated 2026-11-21 23:33 by `python ai/title_classifier.py train`.

**Data:** 770 labelled titles in 70 groups ({'demo': 770}); labels {'productive': 311, 'distracting': 288, 'neutral': 171}.

> **770 of the titles are generated demo data.** These numbers show that the pipeline works and that the evaluation is honest; they are *not* an estimate of accuracy on your real browsing. Label real titles (`source = 'user'`) and retrain with `--source user` to measure that.

## Two questions

- **Known sites:** a new title from a site or pattern the model has seen examples of (cross-validation grouped by exact title, so no duplicate is on both sides). The common case.
- **Unseen sites:** a title from a site or pattern it has never seen (cross-validation grouped by template). The hard case.

Real use falls in between: most browsing is on a handful of familiar sites, plus the occasional new one.

## Model comparison (macro-F1, 5-fold grouped cross-validation)

| Model | Known sites | Unseen sites | Log loss (unseen) |
|---|---|---|---|
| Complement NB, words + chars **(chosen)** | 0.902 | 0.740 | 0.896 |
| Linear SVM, words + chars (calibrated) | 0.897 | 0.684 | 0.784 |
| Logistic regression, words + chars (C=1) | 0.895 | 0.666 | 0.777 |
| Logistic regression, words + chars (C=5) | 0.892 | 0.659 | 0.770 |
| Naive Bayes, words (previous model) | 0.866 | 0.644 | 0.671 |
| Majority class (baseline) | 0.242 | 0.243 | 8.666 |

**Headline estimate for unseen sites (nested grouped CV): macro-F1 0.729 +/- 0.104.** The model was chosen inside each outer fold without seeing that fold's templates (choices: Complement NB, words + chars (5x)), so this number is not inflated by picking the winner on its own test data.

For contrast, a plain random split would report **0.967** for the chosen model. The gap is what near-duplicate titles do to a careless evaluation.

## Chosen model on unseen sites

- Confidence threshold **0.94**: the lowest that keeps precision at least 90%. At it, the model labels **68%** of productive/distracting titles with precision **0.90**; everything else keeps its app's default category. Being unsure and staying quiet is the intended behaviour.

```
              precision    recall  f1-score   support

  productive       0.80      0.90      0.84       311
     neutral       0.62      0.54      0.57       171
 distracting       0.83      0.77      0.80       288

    accuracy                           0.77       770
   macro avg       0.75      0.74      0.74       770
weighted avg       0.77      0.77      0.77       770
```

Confusion matrix (rows = true, columns = predicted):

| | productive | neutral | distracting |
|---|---|---|---|
| **productive** | 280 | 23 | 8 |
| **neutral** | 41 | 92 | 38 |
| **distracting** | 31 | 34 | 223 |

## Most confident mistakes (unseen sites)

| Confidence | Title | True | Predicted |
|---|---|---|---|
| 1.00 | JavaScript std::thread - W3Schools - Brave | distracting | productive |
| 1.00 | Machine Learning Unit 19 lecture notes.pdf - Microsoft​ Edge | distracting | productive |
| 1.00 | Discrete Maths Unit 8 lecture notes.pdf — Mozilla Firefox | distracting | productive |
| 1.00 | Explain Paging and Segmentation with an example - ChatGPT - Microsoft​ Edge | distracting | productive |
| 1.00 | Budget 2026 highlights / The Hindu - Google Chrome | neutral | distracting |
| 1.00 | Your Orders - Amazon.in — Mozilla Firefox | neutral | distracting |
| 1.00 | Your Orders - Amazon.in - Microsoft​ Edge | neutral | distracting |
| 1.00 | Your Orders - Amazon.in - Google Chrome | neutral | distracting |
| 1.00 | Your Orders - Amazon.in - Brave | neutral | distracting |
| 1.00 | Your Orders - Amazon.in | neutral | distracting |
| 1.00 | Budget 2026 highlights / Times of India - Brave | neutral | distracting |
| 1.00 | Australia vs England, Live Cricket Score - Cricbuzz - Microsoft​ Edge | productive | distracting |

Some mistakes are deliberate label noise: the demo data flips about 2% of labels, like a tired human labeller.

## What this means

- The model is reliable on sites it has examples of, and much weaker on sites it has never seen: a title classifier can only learn the vocabulary it is shown. More *different* sites in the training data helps far more than more titles from the same site.
- Only the window title is used. A title like "YouTube" on its own carries no information about the video.
- The label policy (what counts as productive) is a choice; the model learns whatever the labels say.
