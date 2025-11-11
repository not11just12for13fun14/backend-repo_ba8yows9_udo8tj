"""
Database Schemas for Event Platform

Each Pydantic model represents a collection in MongoDB. The collection name is the lowercase of the class name.

Collections:
- Organization ("organization")
- Admin ("admin")
- Event ("event")
"""

from pydantic import BaseModel, Field, HttpUrl, EmailStr
from typing import Optional, List
from datetime import datetime


class Organization(BaseModel):
    """
    Organizations that can create events.
    Collection name: "organization"
    """
    name: str = Field(..., description="Organization name")
    email: EmailStr = Field(..., description="Contact email")
    password_hash: str = Field(..., description="Password hash (sha256)")
    verified: bool = Field(False, description="Whether organization is verified")
    description: Optional[str] = Field(None, description="About the organization")
    website: Optional[HttpUrl] = Field(None, description="Website URL")


class Admin(BaseModel):
    """
    Admin users who can approve events and verify organizations.
    Collection name: "admin"
    """
    email: EmailStr = Field(..., description="Admin email")
    password_hash: str = Field(..., description="Password hash (sha256)")
    name: Optional[str] = Field(None, description="Admin name")


class Event(BaseModel):
    """
    Events created by organizations.
    Collection name: "event"
    """
    title: str = Field(..., description="Event title")
    description: str = Field(..., description="Event description")
    poster_url: Optional[str] = Field(None, description="Poster image URL")
    google_form_url: Optional[str] = Field(None, description="Google Forms registration link")
    venue: str = Field(..., description="Location of the event")
    
    # Event timing
    event_start: datetime = Field(..., description="Event start date and time (ISO)")
    event_end: Optional[datetime] = Field(None, description="Event end date and time (ISO)")

    # Registration window
    registration_start: datetime = Field(..., description="Registration opens (ISO)")
    registration_end: datetime = Field(..., description="Registration closes (ISO)")

    # Categorization
    category: str = Field(..., description="Category such as 'tech', 'non-tech', 'cultural'")

    # Ownership and moderation
    organization_id: str = Field(..., description="ID of creating organization")
    organization_name: Optional[str] = Field(None, description="Denormalized org name for quick reads")
    approved: bool = Field(False, description="Whether event is approved and visible")
    approved_by: Optional[str] = Field(None, description="Admin ID/email who approved")

    # Computed/aux fields
    is_org_verified: Optional[bool] = Field(None, description="Snapshot of org verification at creation time")
