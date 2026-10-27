# BRD: Internal Knowledge Search

Business owner: Director of Customer Support

## Overview
Support agents waste time searching across the wiki, old tickets and policy PDFs. We want one search box that finds the right answer quickly.

## Business Objectives
- Reduce average ticket handling time by 15%.
- Improve first-contact resolution.

## Scope
### In Scope
- Search over wiki pages, resolved tickets and policy documents.
### Out of Scope
- Customer-facing search.

## Functional Requirements
- FR-01 [Must] Agents search across wiki, resolved tickets and policy PDFs from a single search box.
- FR-02 [Must] Results must be fast and relevant.
- FR-03 [Must] Agents only see documents they are permitted to see.
- FR-04 [Should] Agents can filter results by source and date.
- FR-05 [Should] Agents can give thumbs-up or thumbs-down feedback on results, etc.
- FR-06 [Could] Search should be smart and suggest answers as needed.

## Integrations
- INT-01 Confluence wiki API.
- INT-02 Ticketing system API.
- INT-03 Policy document share (SharePoint).

## Constraints
- Team of 5 engineers.
- Timeline TBD.
