# frozen_string_literal: true

require "json"
require "pathname"
require "uri"
require "yaml"

REPOSITORY_ROOT = Pathname.new(File.expand_path("..", __dir__))
errors = []

yaml_files = Dir[
  REPOSITORY_ROOT.join("resources/**/*.{yaml,yml}"),
  REPOSITORY_ROOT.join(".github/**/*.{yaml,yml}")
].sort

yaml_files.each do |path|
  begin
    YAML.load_stream(File.read(path))
  rescue StandardError => error
    errors << "#{Pathname.new(path).relative_path_from(REPOSITORY_ROOT)}: invalid YAML: #{error.message}"
  end
end

Dir[REPOSITORY_ROOT.join("resources/**/*.json")].sort.each do |path|
  begin
    JSON.parse(File.read(path))
  rescue JSON::ParserError => error
    errors << "#{Pathname.new(path).relative_path_from(REPOSITORY_ROOT)}: invalid JSON: #{error.message}"
  end
end

markdown_files = Dir[
  REPOSITORY_ROOT.join("README.md"),
  REPOSITORY_ROOT.join("docs/**/*.md"),
  REPOSITORY_ROOT.join("misc/**/*.md"),
  REPOSITORY_ROOT.join("terraform/**/*.md")
].sort.map { |path| Pathname.new(path) }

anchors_by_file = {}
markdown_files.each do |path|
  duplicate_counts = Hash.new(0)
  anchors = []
  File.readlines(path).each do |line|
    match = line.match(/^\s{0,3}\#{1,6}\s+(.+?)\s*#*\s*$/)
    next unless match

    heading = match[1]
      .gsub(/<[^>]+>/, "")
      .gsub(/\[([^\]]+)\]\([^)]*\)/, '\\1')
      .gsub(/[`*_~]/, "")
      .downcase
      .gsub(/[^\p{L}\p{N}\p{M} _-]/u, "")
      .strip
      .gsub(/\s+/, "-")

    count = duplicate_counts[heading]
    duplicate_counts[heading] += 1
    anchors << (count.zero? ? heading : "#{heading}-#{count}")
  end
  anchors_by_file[path.cleanpath] = anchors.to_h { |anchor| [anchor, true] }
end

markdown_files.each do |source|
  contents = File.read(source)
  contents.to_enum(:scan, /\[[^\]]*\]\(([^)]+)\)/).each do
    match = Regexp.last_match
    raw_link = match[1]
    link = raw_link.strip.sub(/^</, "").sub(/>$/, "")
    next if link.match?(/\A(?:https?:|mailto:)/)

    destination = link.split(/\s+["']/, 2).first
    path_part, anchor = destination.split("#", 2)
    path_part = URI::DEFAULT_PARSER.unescape(path_part.to_s)
    target = path_part.empty? ? source : source.dirname.join(path_part).cleanpath

    line_number = contents[0...match.begin(0)].count("\n") + 1
    location = "#{source.relative_path_from(REPOSITORY_ROOT)}:#{line_number}"
    unless target.file?
      errors << "#{location}: missing local link target #{destination.inspect}"
      next
    end

    next if anchor.nil? || anchor.empty? || target.extname.downcase != ".md"

    decoded_anchor = URI::DEFAULT_PARSER.unescape(anchor).downcase
    unless anchors_by_file.fetch(target, {}).key?(decoded_anchor)
      errors << "#{location}: missing anchor ##{decoded_anchor} in #{target.relative_path_from(REPOSITORY_ROOT)}"
    end
  end
end

if errors.empty?
  puts "Repository YAML, JSON, and local Markdown links are valid."
else
  warn errors.join("\n")
  exit 1
end
