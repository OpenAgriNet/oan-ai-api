from helpers.amharic_numerals import replace_numbers_with_amharic_words

text = "በአመያ ገበያ የተደባለቀ (ሰርገኛ) ጤፍ ዋጋ ከ 12,550 እስከ 12,600 ብር"
print(f"Original: {text}")
converted = replace_numbers_with_amharic_words(text)
print(f"Converted: {converted}")

text2 = "100"
print(f"100: {replace_numbers_with_amharic_words(text2)}")

text3 = "12"
print(f"12: {replace_numbers_with_amharic_words(text3)}")
