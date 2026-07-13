# Advanced NLP, political-corpus and multimodal analysis plan

## Evidence levels

1. **Computed corpus evidence:** counts, dates, document frequencies, hashes and deterministic derived tables.
2. **Model-assisted discovery:** NER, topics, zero-shot frames, OCR, image captions, objects, clusters and cross-modal similarity.
3. **Validated interpretation:** human-reviewed concordances and images coded under an explicit codebook. Only this level should support substantive claims about framing, coded language or visual function.

## Text analysis

The repository supports publication trends, article length and readability, lexical diversity, unigram and n-gram frequencies, matched-comparator keyness, collocations, concordance candidates, named entities, actor co-occurrence, dependency-based predication candidates, multi-seed topic modelling and diachronic distributions. Topic runs use three seeds and report assignment stability rather than presenting one run as objective.

## Political-discourse analysis

The code retrieves candidate passages for security, economy, national identity, law/order, democracy, welfare, family, institutions and mobilisation. It also retrieves possible authorisation, moral evaluation, rationalisation and narrative legitimation. These categories are provisional and should be revised after corpus familiarisation. Actor networks encode only sentence co-occurrence. Automated sentiment or toxicity is deliberately not a central method because coded, ironic, quoted and strategically ambiguous political discourse can defeat generic classifiers.

A separate candidate queue combines keyness and collocation evidence. It does not label terms as dog whistles. Reviewers must document literal meaning, proposed coded function, alternative readings, dispersion, context, confidence and amplification risk before moving an item into `analysis/coded_language_glossary.csv`.

## Image analysis

The image pipeline records dimensions, perceptual duplicates and basic visual features; optionally performs OCR, neutral caption generation, provisional visual classification and zero-shot object detection; embeds images for clustering; and links each image to its article title, lead, explicit caption and OCR. It supports analysis of recurring symbols and branding, event and mobilisation imagery, portraits versus crowds, screenshots and documents as evidence, repeated image reuse, visual changes over time, and whether images are redundant, illustrative, complementary, evidential or weakly aligned with the text.

The pipeline does not perform face recognition, identify people from appearance, infer ethnicity, religion, health, sexuality or political affiliation, or infer organisational links from co-occurrence. Low similarity is a review signal, not evidence of contradiction or deception.

## Human validation

Sample by year, article topic, image cluster, high/low model confidence and provisional relation. Two coders should independently annotate a manageable subset, revise the codebook, report agreement only after actual calculation, and adjudicate disagreements. Preserve model scores so that false positives and false negatives can be analysed rather than hidden.
