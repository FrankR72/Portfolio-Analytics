import sec2md










    
pages = sec2md.convert_to_markdown(html_path.read_bytes(), return_pages=True)
sections = sec2md.extract_sections(pages, filing_type="10-K")