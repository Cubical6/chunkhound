<?php
namespace Acme\Notes\Api;
use Acme\Notes\Api\Data\NoteInterface;
interface NoteRepositoryInterface
{
    public function save(NoteInterface $note);
}
