import re

def number_to_amharic_words(n):
    """
    Converts an integer number to its Amharic word representation.
    Supports numbers up to 999,999,999.
    """
    if n == 0:
        return "ዜሮ"  # Zero

    ones = {
        1: "አንድ", 2: "ሁለት", 3: "ሦስት", 4: "አራት", 5: "አምስት",
        6: "ስድስት", 7: "ሰባት", 8: "ስምንት", 9: "ዘጠኝ"
    }

    tens = {
        10: "አሥር", 20: "ሃምሳ", 30: "ሰላሳ", 40: "አርባ", 50: "ሃምሳ",
        60: "ስልሳ", 70: "ሰባ", 80: "ሰማንያ", 90: "ዘጠና"
    }
    # Note: 20 and 50 both mapped to 'ሃምሳ' in some contexts? 
    # Wait, 20 is "ሀያ" (Haya), 50 is "ሃምሳ" (Hamsa). My memory/sources usage.
    # Let me correct the map.
    
    tens_corrected = {
        10: "አሥር", 20: "ሀያ", 30: "ሰላሳ", 40: "አርባ", 50: "ሃምሳ",
        60: "ስልሳ", 70: "ሰባ", 80: "ሰማንያ", 90: "ዘጠና"
    }
    
    # Exceptions between 10 and 20 (like 11 = asra and)
    # Actually standard is "Asra And" (11), "Asra Hulet" (12).
    # So 10 is 'Asir', but prefix is 'Asra' for 11-19.
    
    def convert_below_100(num):
        if num == 0: return ""
        if num < 10:
            return ones[num]
        if num < 20:
            rem = num - 10
            if rem == 0: return "አሥር"
            return "አሥራ " + ones[rem]
        
        # 20+
        ten_val = (num // 10) * 10
        rem = num % 10
        word = tens_corrected[ten_val]
        if rem > 0:
            word += " " + ones[rem]
        return word

    def convert_below_1000(num):
        if num == 0: return ""
        if num < 100:
            return convert_below_100(num)
        
        hundreds = num // 100
        remainder = num % 100
        
        word = ""
        # 100 is just "Meto" (not And Meto usually, but sometimes).
        # Usually "And Meto" is specific. Let's use simple "Meto" if hundreds==1? 
        # No, "Meto" implies 100.
        if hundreds == 1:
             word = "መቶ"
        else:
             word = convert_below_100(hundreds) + " መቶ"
             
        if remainder > 0:
            word += " " + convert_below_100(remainder)
        return word

    parts = []
    
    # Millions
    millions = n // 1000000
    n %= 1000000
    if millions > 0:
        parts.append(convert_below_1000(millions) + " ሚሊዮን")
        
    # Thousands
    thousands = n // 1000
    n %= 1000
    if thousands > 0:
        # If 1000, usually just "Shih" (Meto Shih? No). 
        # 1000 is "Shih". 2000 is "Hulet Shih".
        # 1000 = "And Shih" or just "Shih"? typically "Shih" or "And Shih".
        # Let's use "Shih" if exactly 1000? 
        # Actually standard is "And Shih" if emphatic, but commonly just "Shih" isn't number.
        # "1000 birr" -> "Shih Birr". 
        # Let's handle 1 specially or use 'And Shih'. 'And Shih' is safer.
        if thousands == 1:
             parts.append("አንድ ሺህ")
        else:
             parts.append(convert_below_1000(thousands) + " ሺህ")

    # Remainder (Hundreds)
    if n > 0:
        parts.append(convert_below_1000(n))
        
    return " ".join(parts)


def replace_numbers_with_amharic_words(text):
    """
    Finds numeric sequences (including comma separated like 12,000) 
    and replaces them with Amharic words.
    """
    def replace(match):
        num_str = match.group(0).replace(',', '')
        if not num_str.isdigit(): return match.group(0)
        
        val = int(num_str)
        return number_to_amharic_words(val)

    # Regex to match numbers like 123 | 12,345
    # Does not handle decimals for now (prices usually whole or handled by TTS)
    pattern = r'\b\d{1,3}(?:,\d{3})*\b|\b\d+\b'
    return re.sub(pattern, replace, text)
