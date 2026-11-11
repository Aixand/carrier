"""Authenticated budget ingestion with fixed routes and transactional delivery."""
import json
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator


class BudgetEvent(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    event_id: str = Field(min_length=1, max_length=193)
    source_id: str = Field(min_length=1, max_length=200)
    event: Literal['budget.threshold_crossed', 'budget.test']
    auth_profile: str = Field(min_length=1, max_length=200)
    observed_at: float = Field(ge=0)
    window: Literal['weekly'] | None = None
    bucket: str | None = Field(default=None, max_length=200)
    thresholds: list[float] | None = Field(default=None, min_length=1, max_length=101)
    remaining_percent: float | None = Field(default=None, ge=0, le=100)
    resets_at: float | None = Field(default=None, ge=0)
    test: bool = False

    @model_validator(mode='after')
    def valid_event(self):
        if self.event == 'budget.test':
            if not self.test:
                raise ValueError('Test events must be explicitly marked')
        elif (self.test or self.window != 'weekly' or not self.bucket or not self.thresholds
              or self.remaining_percent is None
              or any(not 0 <= t <= 100 or self.remaining_percent > t for t in self.thresholds)):
            raise ValueError('Invalid threshold event')
        return self


def register(app, store, identity):
    def source(session=Depends(identity)):
        with store.db() as db:
            route = db.execute('SELECT * FROM budget_sources WHERE address = ?', (session['address'],)).fetchone()
        if route is None:
            raise HTTPException(403, 'Budget source credentials required')
        return dict(route)

    @app.get('/budget-source')
    def describe(route=Depends(source)):
        return route

    @app.post('/events/budget')
    def ingest(body: BudgetEvent, route=Depends(source)):
        if body.source_id != route['address']:
            raise HTTPException(403, 'Source identity mismatch')
        payload = json.dumps(body.model_dump(exclude_none=True), sort_keys=True, separators=(',', ':'))
        with store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            original = db.execute('SELECT * FROM budget_events WHERE source = ? AND event_id = ?',
                                  (route['address'], body.event_id)).fetchone()
            if original:
                if original['payload'] != payload:
                    raise HTTPException(409, 'Event ID already used with different content')
                return {'status': 'stored', 'event_id': body.event_id, 'message_id': original['message_id']}
            key = 'budget:' + body.event_id
            if db.execute('SELECT 1 FROM messages WHERE sender = ? AND message_id = ?',
                          (route['address'], key)).fetchone():
                raise HTTPException(409, 'Event message key is already in use')
            cursor = db.execute('INSERT INTO messages(sender, recipient, content, message_id) VALUES (?, ?, ?, ?)',
                                (route['address'], route['recipient'], payload, key))
            message_id = cursor.lastrowid
            db.execute('INSERT INTO budget_events(source, event_id, payload, message_id) VALUES (?, ?, ?, ?)',
                       (route['address'], body.event_id, payload, message_id))
        return {'status': 'stored', 'event_id': body.event_id, 'message_id': message_id}
