#!/bin/bash
mkdir -p assets/test_data/En_voice
mkdir -p assets/test_data/Am_voice

# Create queries.csv
echo "query_id,query_text
1,What is the weather in Mumbai?
2,How to grow tomatoes?
3,Market price of onion in Nashik?" > assets/test_data/queries.csv

# Generate English Audio
say -v Samantha -o assets/test_data/En_voice/query1.m4a "What is the weather in Mumbai?"
say -v Samantha -o assets/test_data/En_voice/query2.m4a "How to grow tomatoes?"

# Generate Amharic Audio (Simulated with English or generic voice if Amharic not available, 
# since 'say' might not support Amharic nicely without specific voice. 
# We'll just use English audio for the test connectivity, the backend might just transcribe it as English or gibberish Amharic, 
# but it tests the pipeline.)
say -v Samantha -o assets/test_data/Am_voice/query1.m4a "What is the weather in Mumbai?"

echo "Test data created in assets/test_data"
