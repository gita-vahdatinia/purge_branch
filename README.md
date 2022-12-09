# Delete and Notify of Stale Branches Using Github Actions
Add this Github Action to your repo to notify you when branches are stale and delete them if no action is taken. 
If you would like to keep your branch alive, you may prefix it with `keep-alive-` 
It pulls the slack credentials from Github, thus your slack and github account must be associated with the same email.

## Usage

You can use the action from this example repository:

```yml
name: Purge Branches
on:
  schedule:
    - cron: '0 10 * * *' # every day @ 10 AM UTC
jobs:
  purgeBranches:
    runs-on: ubuntu-latest
    steps:
      - name: Delete & Notify Branches
        uses: gita-vahdatinia/purge-branchn@v1
        with:
            token: ${{ secrets.GITHUB_TOKEN }}
            days-to-notify: 50
            days-to-delete: 100

```
