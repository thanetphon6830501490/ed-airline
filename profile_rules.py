import unicodedata

def validate_optional_text(value,label):
    if not isinstance(value,str) or any(not (c.isspace() or unicodedata.category(c)[0] in ('L','M')) for c in value):
        raise ValueError(label+'กรอกได้เฉพาะตัวอักษรและช่องว่าง ห้ามตัวเลขหรือสัญลักษณ์')

def validate_profile_text(profile):
    validate_optional_text(profile.get('ethnicity',''),'เชื้อชาติ')
    validate_optional_text(profile.get('religion',''),'ศาสนา')
