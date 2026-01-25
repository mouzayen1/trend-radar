"""
Stopwords and entity validation for Trend Radar 2.0
Only allow product/project names, not generic tech terms
"""

import re

# Comprehensive stopwords list
STOPWORDS = {
    # Tech acronyms
    'gpu', 'cpu', 'api', 'cli', 'tui', 'ui', 'ux', 'sdk', 'ide', 'sql', 'css',
    'html', 'json', 'xml', 'http', 'https', 'rest', 'ssh', 'dns', 'ssl', 'tls',
    'ram', 'ssd', 'hdd', 'npc', 'rpg', 'fps', 'rpc', 'grpc', 'jwt', 'oauth',
    'cdn', 'aws', 'gcp', 'tcp', 'udp', 'url', 'uri', 'dom', 'svg', 'png', 'jpg',
    'gif', 'pdf', 'csv', 'yaml', 'yml', 'toml', 'ini', 'env', 'npm', 'pip', 'gem',
    'apt', 'yum', 'brew', 'git', 'svn', 'hg', 'ftp', 'sftp', 'smtp', 'imap',
    'pop', 'ldap', 'saml', 'sso', 'mfa', 'otp', 'rsa', 'aes', 'sha', 'md5',
    'utf', 'ascii', 'iso', 'ieee', 'rfc', 'ansi', 'posix', 'unix', 'bsd',
    'gnu', 'gpl', 'mit', 'apache', 'llm', 'nlp', 'ml', 'dl', 'cnn', 'rnn',
    'lstm', 'gan', 'vae', 'rag', 'rlhf', 'lora', 'peft', 'cuda', 'rocm',
    'vulkan', 'opengl', 'directx', 'webgl', 'wasm', 'webgpu', 'simd', 'avx',

    # Common tech nouns
    'editor', 'app', 'apps', 'web', 'code', 'data', 'file', 'files', 'test',
    'tests', 'build', 'builds', 'server', 'servers', 'client', 'clients',
    'user', 'users', 'admin', 'config', 'configs', 'setup', 'install',
    'update', 'updates', 'release', 'releases', 'version', 'versions',
    'beta', 'alpha', 'launch', 'new', 'show', 'ask', 'hn', 'github', 'repo',
    'repos', 'branch', 'branches', 'commit', 'commits', 'merge', 'pull',
    'push', 'clone', 'fork', 'forks', 'star', 'stars', 'issue', 'issues',
    'bug', 'bugs', 'feature', 'features', 'request', 'requests', 'plugin',
    'plugins', 'extension', 'extensions', 'module', 'modules', 'package',
    'packages', 'library', 'libraries', 'framework', 'frameworks', 'tool',
    'tools', 'utility', 'utilities', 'helper', 'helpers', 'wrapper', 'wrappers',
    'binding', 'bindings', 'driver', 'drivers', 'kernel', 'kernels',
    'daemon', 'daemons', 'service', 'services', 'worker', 'workers',
    'job', 'jobs', 'task', 'tasks', 'queue', 'queues', 'cache', 'caches',
    'database', 'databases', 'db', 'dbs', 'table', 'tables', 'index', 'indexes',
    'query', 'queries', 'schema', 'schemas', 'model', 'models', 'view', 'views',
    'controller', 'controllers', 'route', 'routes', 'endpoint', 'endpoints',
    'middleware', 'handler', 'handlers', 'listener', 'listeners', 'event',
    'events', 'hook', 'hooks', 'callback', 'callbacks', 'promise', 'promises',
    'async', 'await', 'sync', 'thread', 'threads', 'process', 'processes',
    'memory', 'storage', 'disk', 'network', 'socket', 'sockets', 'stream',
    'streams', 'buffer', 'buffers', 'pipe', 'pipes', 'channel', 'channels',
    'message', 'messages', 'signal', 'signals', 'error', 'errors', 'warning',
    'warnings', 'log', 'logs', 'debug', 'info', 'trace', 'metric', 'metrics',
    'monitor', 'monitors', 'alert', 'alerts', 'notification', 'notifications',
    'email', 'emails', 'sms', 'chat', 'bot', 'bots', 'agent', 'agents',
    'assistant', 'assistants', 'ai', 'model', 'neural', 'network', 'layer',
    'node', 'nodes', 'graph', 'graphs', 'tree', 'trees', 'list', 'lists',
    'array', 'arrays', 'map', 'maps', 'set', 'sets', 'stack', 'stacks',
    'heap', 'heaps', 'vector', 'vectors', 'matrix', 'tensor', 'tensors',
    'algorithm', 'algorithms', 'function', 'functions', 'method', 'methods',
    'class', 'classes', 'object', 'objects', 'instance', 'instances',
    'variable', 'variables', 'constant', 'constants', 'parameter', 'parameters',
    'argument', 'arguments', 'return', 'value', 'values', 'type', 'types',
    'interface', 'interfaces', 'trait', 'traits', 'enum', 'enums', 'struct',
    'structs', 'union', 'unions', 'pointer', 'pointers', 'reference', 'references',
    'container', 'image', 'dockerfile', 'compose', 'kubernetes', 'k8s', 'helm',
    'terraform', 'ansible', 'puppet', 'chef', 'vagrant', 'packer',

    # Generic verbs/actions
    'create', 'creating', 'build', 'building', 'make', 'making', 'use', 'using',
    'run', 'running', 'start', 'starting', 'stop', 'stopping', 'deploy',
    'deploying', 'fix', 'fixing', 'add', 'adding', 'remove', 'removing',
    'update', 'updating', 'change', 'changing', 'edit', 'editing', 'delete',
    'deleting', 'read', 'reading', 'write', 'writing', 'load', 'loading',
    'save', 'saving', 'open', 'opening', 'close', 'closing', 'send', 'sending',
    'receive', 'receiving', 'get', 'getting', 'set', 'setting', 'call', 'calling',
    'invoke', 'invoking', 'execute', 'executing', 'process', 'processing',
    'handle', 'handling', 'manage', 'managing', 'configure', 'configuring',
    'initialize', 'initializing', 'setup', 'implement', 'implementing',
    'introduce', 'introducing', 'introduction', 'launch', 'launching',

    # Programming languages (standalone - not as part of project names)
    'python', 'javascript', 'typescript', 'rust', 'go', 'golang', 'java',
    'ruby', 'swift', 'kotlin', 'scala', 'clojure', 'elixir', 'erlang',
    'haskell', 'ocaml', 'fsharp', 'csharp', 'cpp', 'c++', 'fortran',
    'cobol', 'pascal', 'delphi', 'lua', 'perl', 'php', 'r', 'julia',
    'matlab', 'dart', 'nim', 'zig', 'v', 'crystal', 'groovy', 'bash',
    'powershell', 'zsh', 'fish', 'tcl', 'awk', 'sed', 'vim', 'emacs',

    # Common English words
    'the', 'a', 'an', 'and', 'or', 'but', 'if', 'then', 'else', 'when',
    'where', 'what', 'which', 'who', 'whom', 'whose', 'why', 'how',
    'this', 'that', 'these', 'those', 'here', 'there', 'now', 'then',
    'today', 'yesterday', 'tomorrow', 'year', 'years', 'month', 'months',
    'week', 'weeks', 'day', 'days', 'hour', 'hours', 'minute', 'minutes',
    'second', 'seconds', 'time', 'times', 'first', 'last', 'next', 'previous',
    'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten',
    'hundred', 'thousand', 'million', 'billion', 'all', 'any', 'some', 'none',
    'each', 'every', 'both', 'few', 'more', 'most', 'other', 'another',
    'such', 'same', 'different', 'own', 'good', 'better', 'best', 'bad',
    'worse', 'worst', 'big', 'bigger', 'biggest', 'small', 'smaller', 'smallest',
    'large', 'larger', 'largest', 'long', 'longer', 'longest', 'short',
    'shorter', 'shortest', 'high', 'higher', 'highest', 'low', 'lower', 'lowest',
    'fast', 'faster', 'fastest', 'slow', 'slower', 'slowest', 'easy', 'easier',
    'easiest', 'hard', 'harder', 'hardest', 'simple', 'simpler', 'simplest',
    'complex', 'modern', 'old', 'older', 'oldest', 'young', 'younger', 'youngest',
    'free', 'open', 'closed', 'public', 'private', 'internal', 'external',
    'local', 'remote', 'global', 'static', 'dynamic', 'native', 'cross',
    'multi', 'single', 'double', 'triple', 'full', 'empty', 'null', 'void',
    'true', 'false', 'yes', 'no', 'on', 'off', 'up', 'down', 'left', 'right',
    'top', 'bottom', 'front', 'back', 'in', 'out', 'into', 'from', 'to',
    'at', 'by', 'for', 'with', 'without', 'about', 'above', 'below',
    'between', 'under', 'over', 'through', 'during', 'before', 'after',
    'while', 'until', 'unless', 'although', 'because', 'since', 'so',
    'just', 'only', 'also', 'too', 'very', 'really', 'actually', 'probably',
    'maybe', 'perhaps', 'always', 'never', 'often', 'sometimes', 'usually',
    'we', 'us', 'our', 'ours', 'you', 'your', 'yours', 'they', 'them',
    'their', 'theirs', 'he', 'him', 'his', 'she', 'her', 'hers', 'it', 'its',
    'i', 'me', 'my', 'mine', 'myself', 'yourself', 'himself', 'herself',
    'itself', 'ourselves', 'themselves', 'anyone', 'everyone', 'someone',
    'no one', 'nobody', 'everybody', 'somebody', 'anything', 'everything',
    'something', 'nothing', 'can', 'could', 'will', 'would', 'shall', 'should',
    'may', 'might', 'must', 'need', 'dare', 'used', 'ought', 'had', 'has',
    'have', 'having', 'do', 'does', 'did', 'doing', 'done', 'be', 'am', 'is',
    'are', 'was', 'were', 'been', 'being', 'get', 'got', 'getting', 'let',
    'lets', 'say', 'says', 'said', 'saying', 'see', 'sees', 'saw', 'seen',
    'seeing', 'know', 'knows', 'knew', 'known', 'knowing', 'think', 'thinks',
    'thought', 'thinking', 'want', 'wants', 'wanted', 'wanting', 'like',
    'likes', 'liked', 'liking', 'look', 'looks', 'looked', 'looking',
    'find', 'finds', 'found', 'finding', 'give', 'gives', 'gave', 'given',
    'giving', 'take', 'takes', 'took', 'taken', 'taking', 'come', 'comes',
    'came', 'coming', 'go', 'goes', 'went', 'gone', 'going', 'put', 'puts',
    'putting', 'try', 'tries', 'tried', 'trying', 'work', 'works', 'worked',
    'working', 'help', 'helps', 'helped', 'helping', 'show', 'shows', 'showed',
    'shown', 'showing', 'tell', 'tells', 'told', 'telling', 'ask', 'asks',
    'asked', 'asking', 'seem', 'seems', 'seemed', 'seeming', 'feel', 'feels',
    'felt', 'feeling', 'leave', 'leaves', 'left', 'leaving', 'keep', 'keeps',
    'kept', 'keeping', 'begin', 'begins', 'began', 'begun', 'beginning',
    'end', 'ends', 'ended', 'ending', 'world', 'game', 'games', 'video',
    'videos', 'image', 'images', 'photo', 'photos', 'picture', 'pictures',
    'music', 'sound', 'sounds', 'voice', 'voices', 'text', 'texts', 'word',
    'words', 'number', 'numbers', 'letter', 'letters', 'name', 'names',
    'title', 'titles', 'link', 'links', 'page', 'pages', 'site', 'sites',
    'post', 'posts', 'comment', 'comments', 'reply', 'replies', 'thread',
    'threads', 'forum', 'forums', 'board', 'boards', 'group', 'groups',
    'team', 'teams', 'company', 'companies', 'business', 'businesses',
    'project', 'projects', 'product', 'products', 'platform', 'platforms',
    'system', 'systems', 'solution', 'solutions', 'problem', 'problems',
    'question', 'questions', 'answer', 'answers', 'example', 'examples',
    'tutorial', 'tutorials', 'guide', 'guides', 'documentation', 'docs',
    'manual', 'manuals', 'reference', 'spec', 'specs', 'standard', 'standards',
    'protocol', 'protocols', 'format', 'formats', 'pattern', 'patterns',
    'design', 'designs', 'architecture', 'structure', 'structures',
    'component', 'components', 'element', 'elements', 'part', 'parts',
    'piece', 'pieces', 'section', 'sections', 'chapter', 'chapters',
    'point', 'points', 'step', 'steps', 'stage', 'stages', 'phase', 'phases',
    'level', 'levels', 'tier', 'tiers', 'layer', 'layers', 'mode', 'modes',
    'state', 'states', 'status', 'option', 'options', 'setting', 'settings',
    'preference', 'preferences', 'choice', 'choices', 'decision', 'decisions',
    'reason', 'reasons', 'cause', 'causes', 'effect', 'effects', 'result',
    'results', 'outcome', 'outcomes', 'impact', 'impacts', 'benefit', 'benefits',
    'advantage', 'advantages', 'disadvantage', 'disadvantages', 'pro', 'pros',
    'con', 'cons', 'strength', 'strengths', 'weakness', 'weaknesses',
    'risk', 'risks', 'opportunity', 'opportunities', 'challenge', 'challenges',
    'issue', 'issues', 'concern', 'concerns', 'matter', 'matters', 'thing',
    'things', 'stuff', 'item', 'items', 'object', 'objects', 'entity', 'entities',
    'instance', 'instances', 'case', 'cases', 'situation', 'situations',
    'condition', 'conditions', 'context', 'contexts', 'environment', 'environments',
    'space', 'spaces', 'area', 'areas', 'region', 'regions', 'zone', 'zones',
    'domain', 'domains', 'field', 'fields', 'scope', 'scopes', 'range', 'ranges',
    'limit', 'limits', 'boundary', 'boundaries', 'border', 'borders', 'edge',
    'edges', 'corner', 'corners', 'center', 'middle', 'side', 'sides',
    'way', 'ways', 'path', 'paths', 'road', 'roads', 'route', 'routes',
    'direction', 'directions', 'position', 'positions', 'location', 'locations',
    'place', 'places', 'spot', 'spots', 'source', 'sources', 'target', 'targets',
    'destination', 'destinations', 'origin', 'origins', 'base', 'bases',
    'foundation', 'foundations', 'root', 'roots', 'core', 'cores', 'heart',
    'key', 'keys', 'secret', 'secrets', 'password', 'passwords', 'token', 'tokens',
    'credential', 'credentials', 'permission', 'permissions', 'access', 'role',
    'roles', 'policy', 'policies', 'rule', 'rules', 'law', 'laws', 'term', 'terms',

    # HN specific
    'hn', 'hacker', 'news', 'hackernews', 'yc', 'ycombinator', 'pg', 'dang',
    'flagged', 'dead', 'karma', 'upvote', 'downvote', 'submission', 'submissions',

    # More generic descriptors
    'awesome', 'cool', 'great', 'nice', 'beautiful', 'ugly', 'pretty',
    'amazing', 'incredible', 'fantastic', 'wonderful', 'terrible', 'horrible',
    'interesting', 'boring', 'exciting', 'fun', 'funny', 'serious', 'important',
    'useful', 'useless', 'helpful', 'practical', 'theoretical', 'real', 'fake',
    'official', 'unofficial', 'alternative', 'original', 'copy', 'clone',
    'inspired', 'based', 'powered', 'driven', 'focused', 'oriented', 'centric',
    'friendly', 'native', 'aware', 'ready', 'compatible', 'compliant',
    'secure', 'safe', 'dangerous', 'risky', 'stable', 'unstable', 'reliable',
    'unreliable', 'efficient', 'inefficient', 'effective', 'ineffective',
    'productive', 'unproductive', 'scalable', 'portable', 'flexible', 'rigid',
    'modular', 'monolithic', 'distributed', 'centralized', 'decentralized',
    'lightweight', 'heavyweight', 'minimal', 'minimal', 'maximal', 'optimal',
    'suboptimal', 'perfect', 'imperfect', 'complete', 'incomplete', 'partial',
    'total', 'absolute', 'relative', 'approximate', 'exact', 'precise',
    'accurate', 'inaccurate', 'correct', 'incorrect', 'valid', 'invalid',
    'legal', 'illegal', 'allowed', 'forbidden', 'required', 'optional',
    'mandatory', 'recommended', 'suggested', 'preferred', 'default', 'custom',
    'standard', 'special', 'unique', 'common', 'rare', 'frequent', 'occasional',
    'regular', 'irregular', 'normal', 'abnormal', 'typical', 'atypical',
    'average', 'median', 'mean', 'expected', 'unexpected', 'surprising',
    'obvious', 'hidden', 'visible', 'invisible', 'transparent', 'opaque',
    'clear', 'unclear', 'vague', 'specific', 'general', 'generic', 'abstract',
    'concrete', 'virtual', 'physical', 'digital', 'analog', 'binary', 'decimal',
    'hexadecimal', 'octal', 'linear', 'nonlinear', 'exponential', 'logarithmic',
    'parallel', 'serial', 'sequential', 'concurrent', 'synchronous', 'asynchronous',
    'blocking', 'nonblocking', 'recursive', 'iterative', 'declarative', 'imperative',
    'functional', 'procedural', 'object', 'oriented', 'reactive', 'responsive',

    # Additional generic terms
    'incidental', 'priority', 'major', 'minor', 'patch', 'hotfix', 'bugfix',
    'enhancement', 'improvement', 'optimization', 'refactor', 'refactoring',
    'cleanup', 'migration', 'upgrade', 'downgrade', 'rollback', 'backup',
    'restore', 'recovery', 'maintenance', 'support', 'documentation',
}


def normalize_entity(entity: str) -> str:
    """Normalize entity name for consistent matching"""
    if not entity:
        return ''
    # Remove common prefixes
    entity = re.sub(r'^(Show HN:|Ask HN:|Tell HN:|Launch HN:)\s*', '', entity, flags=re.IGNORECASE)
    # Remove trailing punctuation
    entity = re.sub(r'[.,!?:;\-–—]+$', '', entity)
    # Strip whitespace
    entity = entity.strip()
    return entity.lower()


def is_camel_case(s: str) -> bool:
    """Check if string is CamelCase (e.g., DeepSeek, ChatGPT)"""
    if not s or len(s) < 2:
        return False
    # Must have at least one lowercase followed by uppercase, or uppercase followed by lowercase
    return bool(re.search(r'[a-z][A-Z]|[A-Z][a-z]', s)) and not s.isupper() and not s.islower()


def has_version_number(s: str) -> bool:
    """Check if string contains a version number (e.g., GPT4, Llama3, v2.0)"""
    return bool(re.search(r'\d+\.?\d*|v\d+', s, re.IGNORECASE))


def is_github_repo_format(s: str) -> bool:
    """Check if string is in owner/repo format"""
    return bool(re.match(r'^[\w\-\.]+/[\w\-\.]+$', s))


def is_valid_entity(entity: str, require_signals: int = 0) -> bool:
    """
    Check if an entity is worth tracking/alerting about.
    Returns True only for likely product/project names.
    """
    if not entity:
        return False

    entity = entity.strip()
    normalized = normalize_entity(entity)

    # Must be at least 2 characters
    if len(normalized) < 2:
        return False

    # Check stopwords
    if normalized in STOPWORDS:
        return False

    # Check each word in multi-word entities
    words = normalized.split()

    # Filter common sentence starters
    sentence_starters = {'i', 'a', 'the', 'an', 'my', 'we', 'our', 'this', 'that', 'it', 'on', 'in', 'at', 'to', 'for'}
    if words and words[0] in sentence_starters:
        return False

    if len(words) == 1:
        # Single word - must be special format
        if normalized in STOPWORDS:
            return False
        # Allow if CamelCase, has numbers, or is github format
        if is_camel_case(entity) or has_version_number(entity) or is_github_repo_format(entity):
            return True
        # Allow if it's at least 4 chars and not a stopword
        if len(normalized) >= 4 and normalized not in STOPWORDS:
            return True
        return False

    # Multi-word entity
    # Filter if ALL words are stopwords
    non_stopword_count = sum(1 for w in words if w not in STOPWORDS)
    if non_stopword_count == 0:
        return False

    # Filter if first word is a stopword (likely a sentence fragment)
    if words[0] in STOPWORDS:
        return False

    # Filter if first two words are both stopwords
    if len(words) >= 2 and words[0] in STOPWORDS and words[1] in STOPWORDS:
        return False

    # Filter very long entities (likely sentences, not names)
    if len(entity) > 40:
        return False

    # Filter if it looks like a sentence (too many words)
    if len(words) > 4:
        return False

    # Filter common patterns that aren't product names
    bad_patterns = ['built', 'made', 'created', 'wrote', 'released', 'launched', 'self', 'device', 'roms']
    if any(w in bad_patterns for w in words):
        return False

    # Filter "on-X" patterns that are generic
    if normalized.startswith('on-'):
        return False

    # Filter well-known established tech (not "new trends")
    established_tech = {
        'roms', 'sqlite', 'postgres', 'postgresql', 'mysql', 'redis', 'mongodb',
        'linux', 'windows', 'macos', 'android', 'ios', 'ubuntu', 'debian',
        'chrome', 'firefox', 'safari', 'edge', 'brave',
        'docker', 'kubernetes', 'nginx', 'apache',
        'react', 'vue', 'angular', 'svelte', 'nextjs', 'nuxt',
        'nodejs', 'deno', 'bun',
        'webpack', 'vite', 'rollup', 'esbuild',
        'tensorflow', 'pytorch', 'keras', 'scikit',
        'pandas', 'numpy', 'scipy', 'matplotlib',
        'django', 'flask', 'fastapi', 'express', 'rails',
        'aws', 'azure', 'gcp', 'cloudflare', 'vercel', 'netlify',
        'github', 'gitlab', 'bitbucket',
        'vscode', 'vim', 'neovim', 'emacs', 'sublime',
        'chatgpt', 'openai', 'anthropic', 'claude', 'gemini', 'gpt',
    }
    if normalized in established_tech:
        return False

    return True


def extract_product_name(text: str) -> str | None:
    """
    Extract a likely product/project name from text.
    Looks for CamelCase, quoted names, etc.
    """
    if not text:
        return None

    # Try to find "Show HN: ProductName" pattern
    show_hn = re.search(r'Show HN:\s*([A-Z][A-Za-z0-9]*(?:\s+[A-Z][A-Za-z0-9]*)?)', text)
    if show_hn:
        name = show_hn.group(1).strip()
        if is_valid_entity(name):
            return name

    # Try to find CamelCase words
    camel_cases = re.findall(r'\b([A-Z][a-z]+(?:[A-Z][a-z]+)+)\b', text)
    for cc in camel_cases:
        if is_valid_entity(cc):
            return cc

    # Try to find quoted names
    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', text)
    for q in quoted:
        name = q[0] or q[1]
        if name and is_valid_entity(name):
            return name

    # Try to find names with numbers (GPT4, Llama3)
    with_numbers = re.findall(r'\b([A-Z][A-Za-z]*\d+(?:\.\d+)?)\b', text)
    for wn in with_numbers:
        if is_valid_entity(wn):
            return wn

    return None
