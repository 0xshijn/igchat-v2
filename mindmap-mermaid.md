# igchat-v2 - Mindmap kiến trúc v3.0.0

[README](README.md) | [README (EN)](README_EN.md) | [Tài liệu API](DOCS.md) | [Flowchart](FLOWCHART.md) | [Bridge Docs](bridge/README.md)

```mermaid
mindmap
  root((igchat-v2 v3.0.0))
    Application
      src/main.py & root main.py
        igchat_v2.bot.main_blocking
        InstagramBot runtime
        Bounded LRU cache
        Per-user rate limiter
        Async command router
        Graceful signal shutdown
      src/config.example.json
        cookies placeholder
        prefix
        admin_ids
    Core igchat_v2.core
      Session & Models
        InstagramSession
        UserSummary
        ThreadSummary
        MessageEvent
        SendResult
      HTTP & Network
        httpx AsyncClient pooling
        post_async & get_async
        post_graphql_async
        SSRF guard validate_public_http_url
        Bounded download_public_bytes
      Security & Permissions
        POSIX 0600 & Windows token ACLs
        Data and credential redaction
      Utilities
        Polaris GraphQL payload builders
        Jazoest generator
        Offline threading ID
        JSON prefix parser
    Auth igchat_v2.auth
      Storage
        SessionStorage interface
        FileSessionStorage atomic write
        EnvSessionStorage
      Instagram Web Auth
        Direct inbox bootstrap
        Web AJAX login
        2FA TOTP pyotp
    Bridge igchat_v2.bridge
      BridgeProcess
        Stdin and stdout line JSON-RPC
        Generation-fenced supervisor
        ReconnectPolicy exponential backoff
      BridgeActions
        Direct send and edit
        Unsend and react
        Thread and participant actions
        Typing and mark read
    Go Bridge Engine bridge/
      Binary build/igchat-bridge.exe
      instameow core
        Direct DGW WebSocket
        Slide GraphQL
        MQTT bypass protocol
      Bridge security
        SSRF-safe media pipeline
        Stderr log redactor
        Atomic file permissions
    Direct Messaging igchat_v2.direct
      DirectListener
        Real-time event loop
        Async event hooks
      Messages & Actions
        send_text_message
        edit_text_message
        unsend_text_message
        react_to_message
      Thread Management
        Inbox pagination
        Thread detail & messages
        Change title & theme
        Add & remove participant
        Mute thread REST
      Notes & Media
        Instagram 24h Notes
        Search music notes
        rupload photo & video
    Social Features igchat_v2.social
      Profile
        get_user_profile
        change_bio
      Friendships
        follow_user
        unfollow_user
        remove_follower
        block_user & unblock_user
      Posts & Media
        like_media & save_media
        comment_media & delete_comment
        publish_photo
        shortcode & media_id conversion
      Search & Notifications
        search_users
        fetch_notifications
    Quality Assurance
      pytest test suite
      Go test & vet
      mypy strict type checking
      Black & Ruff code style
```

Mindmap thể hiện tổng quan phân lớp kiến trúc dự án `igchat-v2` v3.0.0. Xem [FLOWCHART.md](FLOWCHART.md) để theo dõi chi tiết luồng xử lý và [DOCS.md](DOCS.md) để tra cứu chữ ký API.
