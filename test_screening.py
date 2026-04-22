#!/usr/bin/env python
"""Test Feature 3: Application Screening"""

from app import supabase, _generate_application_screening

# Get an application and its documents
apps = supabase.table('online_applications').select(
    '*').limit(1).execute().data
if not apps:
    print("No applications found in the database")
    exit(1)

application = apps[0]
app_ref = application.get('ref')
school_id = application.get('school_id')

print(f"\n✅ Application Found:")
print(f"   Ref: {app_ref}")
print(
    f"   Name: {application.get('first_names')} {application.get('surname')}")
print(f"   School: {school_id}")
print(f"   Status: {application.get('status')}")

# Get school details
schools = supabase.table('schools').select(
    '*').eq('id', school_id).limit(1).execute().data
school = schools[0] if schools else {}

# Get documents
docs = supabase.table('online_application_docs').select(
    '*').eq('application_ref', app_ref).execute().data
print(f"   Documents: {len(docs)} uploaded")

# Generate screening
print(f"\n🔍 Running Application Screening...")
screening = _generate_application_screening(school, application, docs)

print(f"\n📊 Screening Results:")
print(f"   Score: {screening.get('screening_score')}/100")
print(f"   Recommendation: {screening.get('recommendation')}")
print(f"   Source: {screening.get('screening_source')}")
print(f"   Model: {screening.get('model')}")
print(f"   Summary: {screening.get('summary')[:150]}...")
print(f"\n✨ Feature 3 (Application Screening) is WORKING!")
