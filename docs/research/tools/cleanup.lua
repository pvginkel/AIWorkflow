-- Pandoc filter that trades LaTeX-specific structure for plain Markdown.
--
-- Everything here exists because the default LaTeX -> GFM conversion emits raw
-- HTML or drops information a reader needs. The output is meant to be read and
-- grepped, not typeset, so anchors and styling lose to legibility.

local stringify = pandoc.utils.stringify

-- Figures are PDF/EPS files that do not survive the trip to Markdown, and a
-- link to a file we never copied is worse than no link at all. Keep the
-- caption, which is the part worth reading.
local function figure_marker(text)
  text = (text or ''):gsub('^%s+', ''):gsub('%s+$', '')
  if text == '' then
    text = 'no caption'
  end
  -- Str, not RawInline: a caption is arbitrary prose and needs the writer's
  -- escaping. "Figure:" carries no Markdown-special characters of its own.
  return pandoc.Emph({ pandoc.Str('Figure: '), pandoc.Str(text) })
end

function Image(image)
  local caption = stringify(image.caption)
  if caption == '' then
    caption = image.src
  end
  return figure_marker(caption)
end

function Figure(figure)
  return pandoc.Para({ figure_marker(stringify(figure.caption.long or figure.caption)) })
end

-- Without --citeproc pandoc renders \cite as nothing at all, which silently
-- turns "as shown by \cite{smith}" into "as shown by". The keys match the
-- \bibitem markers that arxiv_to_md.py injects into the reference list.
function Cite(cite)
  -- When citeproc ran it has already replaced the raw \cite with rendered
  -- text; only an untouched citation is still nothing but a RawInline.
  for _, element in ipairs(cite.content) do
    if element.t ~= 'RawInline' then
      return nil
    end
  end

  local ids = {}
  for _, citation in ipairs(cite.citations) do
    ids[#ids + 1] = citation.id
  end
  -- Raw, because the Markdown writer would escape the brackets.
  return pandoc.RawInline('gfm', '[' .. table.concat(ids, '; ') .. ']')
end

-- \textsc has no Markdown equivalent, so the writer falls back to a styled span.
-- Markdown cannot carry the styling anyway; keep the words.
function SmallCaps(smallcaps)
  return smallcaps.content
end

-- \label leaves behind empty spans that the GFM writer can only express as raw
-- HTML; other spans carry text worth keeping but no styling worth keeping.
function Span(span)
  if #span.content == 0 then
    return {}
  end
  return span.content
end

-- Div classes come from LaTeX environments (theorem, definition, thebibliography).
-- Unwrap them, but give the bibliography the heading LaTeX would have printed.
function Div(div)
  if div.classes:includes('thebibliography') then
    -- Level 2 to sit alongside the shifted \section headings, not above them.
    local blocks = pandoc.Blocks({ pandoc.Header(2, 'References') })
    blocks:extend(div.content)
    return blocks
  end
  return div.content
end

-- citeproc appends its reference section at the top level, below the shifted
-- \section headings rather than alongside them. A genuine \section{References}
-- has already been shifted by the time this runs, so a level-1 one is citeproc's.
function Header(header)
  if header.level == 1 and stringify(header.content) == 'References' then
    header.level = 2
    return header
  end
end

-- Cross-references arrive as links carrying data-reference attributes, which
-- again force the writer into raw HTML. Rebuild them as plain Markdown links.
function Link(link)
  return pandoc.Link(link.content, link.target, link.title)
end
